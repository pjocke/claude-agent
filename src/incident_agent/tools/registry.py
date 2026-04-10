from claude_agent_sdk import create_sdk_mcp_server, tool

from incident_agent.tools.remediation import restart_pod, scale_deployment


@tool(
    "restart_pod",
    "Restart a specific Kubernetes pod by name and namespace. Only allowed namespaces can be targeted.",
    {
        "type": "object",
        "properties": {
            "pod_name": {"type": "string", "description": "Name of the pod to restart"},
            "namespace": {"type": "string", "description": "Kubernetes namespace"},
            "dry_run": {"type": "boolean", "description": "If true, only simulate the action", "default": False},
        },
        "required": ["pod_name", "namespace"],
    },
)
async def restart_pod_tool(args: dict) -> dict:
    result = await restart_pod(
        pod_name=args["pod_name"],
        namespace=args["namespace"],
        dry_run=args.get("dry_run", False),
    )
    return {"content": [{"type": "text", "text": result}]}


@tool(
    "scale_deployment",
    "Scale a Kubernetes deployment to a specified number of replicas. Only allowed namespaces can be targeted. Replicas must be between 0 and 20.",
    {
        "type": "object",
        "properties": {
            "deployment": {"type": "string", "description": "Name of the deployment to scale"},
            "namespace": {"type": "string", "description": "Kubernetes namespace"},
            "replicas": {"type": "integer", "description": "Target number of replicas (0-20)"},
            "dry_run": {"type": "boolean", "description": "If true, only simulate the action", "default": False},
        },
        "required": ["deployment", "namespace", "replicas"],
    },
)
async def scale_deployment_tool(args: dict) -> dict:
    result = await scale_deployment(
        deployment=args["deployment"],
        namespace=args["namespace"],
        replicas=args["replicas"],
        dry_run=args.get("dry_run", False),
    )
    return {"content": [{"type": "text", "text": result}]}


ALLOWED_REMEDIATION_TOOLS = [
    "mcp__remediation__restart_pod",
    "mcp__remediation__scale_deployment",
]


def create_remediation_server():
    return create_sdk_mcp_server(
        name="remediation",
        version="1.0.0",
        tools=[restart_pod_tool, scale_deployment_tool],
    )
