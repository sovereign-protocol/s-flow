"""S-Flow manifest and Sovereign host wiring."""

from sovereign import (
    ApplicationFacade,
    ApplicationInstance,
    ApplicationManifest,
    ApplicationServices,
)

from .controller import build_routes
from .facade import FLOW_FACADE_API_VERSION, FlowFacade
from .logic import FlowLogic


APPLICATION_MANIFEST = ApplicationManifest(
    application_id="flow",
    display_name="S-Flow",
    data_schema_version=1,
    asset_package="s_flow.assets",
    ui_file="flow.html",
    css_file="flow.css",
    icon=(
        # Stages in sequence. The square and checkmark read as a
        # checklist, not as something that moves through them (U8).
        '<circle cx="5" cy="12" r="2"></circle>'
        '<circle cx="12" cy="12" r="2"></circle>'
        '<circle cx="19" cy="12" r="2"></circle>'
        '<path d="M7 12h3"></path><path d="M14 12h3"></path>'
    ),
)


def create_application(services: ApplicationServices) -> ApplicationInstance:
    logic = FlowLogic(
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
            facade_api_version=FLOW_FACADE_API_VERSION,
            api=FlowFacade(logic),
        ),
    )

