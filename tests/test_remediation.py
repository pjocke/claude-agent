import pytest

from incident_agent.tools.remediation import restart_pod, scale_deployment


@pytest.mark.asyncio
async def test_restart_pod_dry_run():
    result = await restart_pod("my-pod", "default", dry_run=True)
    assert "DRY RUN" in result
    assert "my-pod" in result
    assert "default" in result


@pytest.mark.asyncio
async def test_restart_pod_stub():
    result = await restart_pod("my-pod", "default")
    assert "STUB" in result


@pytest.mark.asyncio
async def test_restart_pod_disallowed_namespace():
    result = await restart_pod("my-pod", "kube-system")
    assert "Error" in result
    assert "allowlist" in result


@pytest.mark.asyncio
async def test_scale_deployment_dry_run():
    result = await scale_deployment("my-deploy", "production", 3, dry_run=True)
    assert "DRY RUN" in result
    assert "my-deploy" in result
    assert "3" in result


@pytest.mark.asyncio
async def test_scale_deployment_stub():
    result = await scale_deployment("my-deploy", "staging", 5)
    assert "STUB" in result


@pytest.mark.asyncio
async def test_scale_deployment_disallowed_namespace():
    result = await scale_deployment("my-deploy", "kube-system", 3)
    assert "Error" in result


@pytest.mark.asyncio
async def test_scale_deployment_replicas_too_high():
    result = await scale_deployment("my-deploy", "default", 100)
    assert "Error" in result
    assert "20" in result


@pytest.mark.asyncio
async def test_scale_deployment_negative_replicas():
    result = await scale_deployment("my-deploy", "default", -1)
    assert "Error" in result
