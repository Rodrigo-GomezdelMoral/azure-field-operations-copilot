from agent_framework.observability import create_resource, enable_instrumentation, get_meter, get_tracer
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor

from app.config import Settings

SERVICE = "azure-field-operations-copilot"
tracer = get_tracer(SERVICE)
pending_age = get_meter(SERVICE).create_histogram("app.pending_request_age_hours", "h", "age of a pending request")


def configure(settings: Settings) -> None:
    if settings.applicationinsights_connection_string:
        resource, connection = create_resource(service_name=SERVICE), settings.applicationinsights_connection_string
        configure_azure_monitor(connection_string=connection, credential=DefaultAzureCredential(), resource=resource)
    enable_instrumentation(enable_sensitive_data=False)
