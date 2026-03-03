import pgtrigger

from bazis.core.utils.triggers import trigger_name


class TriggerRoleCurrentInRoles(pgtrigger.Trigger):
    """
    Enforce invariant: role_current must exist in roles.
    Applied to user model and its m2m through table.
    """

    name = trigger_name('role_current_in_roles')
    when = pgtrigger.Before
    operation = pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete

    def get_func(self, model):
        UserModel = self._primary_model  # noqa: N806
        roles_field = UserModel._meta.get_field('roles')
        role_current_field = UserModel._meta.get_field('role_current')

        through_model = roles_field.remote_field.through
        through_table = through_model._meta.db_table

        role_current_col = role_current_field.column
        user_pk_col = UserModel._meta.pk.column

        through_user_col = through_model._meta.get_field(UserModel._meta.model_name).column
        through_role_col = through_model._meta.get_field(
            roles_field.related_model._meta.model_name
        ).column

        if model is not UserModel:
            return """
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;

                RETURN NEW;
            """

        return f"""
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;

            IF NEW.{role_current_col} IS NULL THEN
                -- Keep NULL as-is. This allows FK on_delete=SET_NULL when role is deleted.
                RETURN NEW;
            END IF;

            PERFORM 1
                FROM {through_table} th
                WHERE th.{through_user_col} = NEW.{user_pk_col}
                  AND th.{through_role_col} = NEW.{role_current_col}
                LIMIT 1;

            IF NOT FOUND THEN
                -- If role_current is stale/outside roles (e.g. m2m changed before user save),
                -- normalize it to the first available role. Keep NULL if roles are empty.
                SELECT th.{through_role_col}
                    INTO NEW.{role_current_col}
                    FROM {through_table} th
                    WHERE th.{through_user_col} = NEW.{user_pk_col}
                    ORDER BY th.{through_role_col}
                    LIMIT 1;
            END IF;

            RETURN NEW;
        """


class TriggerSetDefaultUserRole(pgtrigger.Trigger):
    """
    Set role_current to the first available role when roles are added/removed.
    Applied to the user model m2m through table.
    """

    name = trigger_name('set_default_user_role')
    when = pgtrigger.After
    operation = pgtrigger.Insert | pgtrigger.Delete

    def get_func(self, model):
        UserModel = self._primary_model  # noqa: N806
        roles_field = UserModel._meta.get_field('roles')
        role_current_field = UserModel._meta.get_field('role_current')

        through_model = roles_field.remote_field.through
        through_table = through_model._meta.db_table
        user_table = UserModel._meta.db_table

        role_current_col = role_current_field.column
        user_pk_col = UserModel._meta.pk.column

        through_user_col = through_model._meta.get_field(UserModel._meta.model_name).column
        through_role_col = through_model._meta.get_field(
            roles_field.related_model._meta.model_name
        ).column

        if model is not through_model:
            return """
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;

                RETURN NEW;
            """

        return f"""
            IF TG_OP = 'INSERT' THEN
                UPDATE {user_table} u
                    SET {role_current_col} = s.{through_role_col}
                    FROM (
                        SELECT th.{through_role_col}
                        FROM {through_table} th
                        WHERE th.{through_user_col} = NEW.{through_user_col}
                        ORDER BY th.{through_role_col}
                        LIMIT 1
                    ) s
                    WHERE u.{user_pk_col} = NEW.{through_user_col}
                      AND u.{role_current_col} IS NULL;

                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE {user_table} u
                    SET {role_current_col} = (
                        SELECT th.{through_role_col}
                        FROM {through_table} th
                        WHERE th.{through_user_col} = OLD.{through_user_col}
                        ORDER BY th.{through_role_col}
                        LIMIT 1
                    )
                    WHERE u.{user_pk_col} = OLD.{through_user_col}
                      AND u.{role_current_col} = OLD.{through_role_col};

                RETURN OLD;
            END IF;

            RETURN NEW;
        """
