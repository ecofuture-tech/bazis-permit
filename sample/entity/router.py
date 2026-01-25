from bazis.core.routing import BazisRouter

from . import routes


router = BazisRouter(tags=['Entity'])
router.register(routes.ChildEntityRouteSet.as_router())
router.register(routes.DependentEntityRouteSet.as_router())
router.register(routes.ExtendedEntityRouteSet.as_router())
router.register(routes.ParentEntityRouteSet.as_router())
