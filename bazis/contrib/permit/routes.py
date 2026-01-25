from django.apps import apps

from bazis.core.routes_abstract.jsonapi import JsonapiRouteBase


class RoleRoute(JsonapiRouteBase):
    """
    Defines the route for handling Role-related operations in the application,
    extending the JsonapiRouteBase to leverage JSON API standards. It specifies the
    model to be used and the actions that can be performed.
    """

    model = apps.get_model('permit.Role')
    actions = ['action_list', 'action_retrieve']
