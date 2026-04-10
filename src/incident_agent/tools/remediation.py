import logging

logger = logging.getLogger(__name__)

ALLOWED_NAMESPACES = {"default", "production", "staging"}
MAX_REPLICAS = 20


async def restart_pod(
    pod_name: str,
    namespace: str,
    dry_run: bool = False,
) -> str:
    logger.info("restart_pod called: pod=%s namespace=%s dry_run=%s", pod_name, namespace, dry_run)

    if namespace not in ALLOWED_NAMESPACES:
        return f"Error: namespace '{namespace}' is not in the allowlist: {sorted(ALLOWED_NAMESPACES)}"

    if dry_run:
        return f"DRY RUN: would restart pod '{pod_name}' in namespace '{namespace}'"

    return f"STUB: restart_pod not yet implemented for pod '{pod_name}' in namespace '{namespace}'"


async def scale_deployment(
    deployment: str,
    namespace: str,
    replicas: int,
    dry_run: bool = False,
) -> str:
    logger.info(
        "scale_deployment called: deployment=%s namespace=%s replicas=%d dry_run=%s",
        deployment, namespace, replicas, dry_run,
    )

    if namespace not in ALLOWED_NAMESPACES:
        return f"Error: namespace '{namespace}' is not in the allowlist: {sorted(ALLOWED_NAMESPACES)}"

    if not 0 <= replicas <= MAX_REPLICAS:
        return f"Error: replicas must be between 0 and {MAX_REPLICAS}, got {replicas}"

    if dry_run:
        return f"DRY RUN: would scale deployment '{deployment}' in namespace '{namespace}' to {replicas} replicas"

    return f"STUB: scale_deployment not yet implemented for deployment '{deployment}' in namespace '{namespace}' to {replicas} replicas"
