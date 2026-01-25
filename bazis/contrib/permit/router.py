from django.utils.translation import gettext_lazy as _

from bazis.core.routing import BazisRouter

from .routes import RoleRoute


router = BazisRouter(tags=[_('Role model')])
router.register(RoleRoute.as_router())
