"""S-decision manifest and Sovereign host wiring."""

from sovereign import (
    ApplicationFacade,
    ApplicationInstance,
    ApplicationManifest,
    ApplicationServices,
)

from .controller import build_routes
from .facade import decision_FACADE_API_VERSION, decisionFacade
from .logic import decisionLogic


APPLICATION_MANIFEST = ApplicationManifest(
    application_id="decision",
    display_name="S-decision",
    data_schema_version=1,
    asset_package="s_decision.assets",
    ui_file="decision.html",
    css_file="decision.css",
    icon=(
        '<path d="M5 4h14v16H5z"></path>'
        '<path d="M8 9l2 2 5-5"></path>'
        '<path d="M8 15h8"></path>'
    ),
)


def create_application(services: ApplicationServices) -> ApplicationInstance:
    logic = decisionLogic(
        services.session,
        dict(services.settings),
        services.collaboration,
    )
    return ApplicationInstance(
        manifest=APPLICATION_MANIFEST,
        logic=logic,
        registration=logic.application_registration(),
        controllers=tuple(build_routes(logic, services)),
        facade=ApplicationFacade(
            application_id=APPLICATION_MANIFEST.application_id,
            facade_api_version=decision_FACADE_API_VERSION,
            api=decisionFacade(logic),
        ),
    )

