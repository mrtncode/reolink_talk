"""Set the integration up inside a real Home Assistant instance.

Runs only when pytest-homeassistant-custom-component is installed
(requirements-test-ha.txt); the lightweight unit-test environments skip it.
Guards against HA API drift (entity platform callbacks, options flow,
service registration/validation) that pure mocks cannot see.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.components.media_player import (  # noqa: E402
    DOMAIN as MP_DOMAIN,
    MediaPlayerEntityFeature,
)
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.reolink_talk.const import DOMAIN  # noqa: E402
from custom_components.reolink_talk.talk import TalkAbility  # noqa: E402

ENTITY_ID = "media_player.reolink_talk_ausfahrt"
ABILITY = TalkAbility(
    duplex="FDX",
    audio_stream_mode="mixAudioStream",
    audio_type="adpcm",
    priority=None,
    sample_rate=16000,
    sample_precision=16,
    length_per_encoder=1024,
    sound_track="mono",
)
EXPECTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
)


@pytest.fixture
async def setup_integration(hass: HomeAssistant, enable_custom_integrations: None):
    """Set up reolink_talk against a (mocked) official reolink config entry."""
    reolink_entry = MockConfigEntry(
        domain="reolink",
        title="Ausfahrt",
        data={
            "host": "127.0.0.1",
            "username": "user",
            "password": "pass",
            "port": 443,
            "use_https": True,
            "baichuan_port": 9000,
        },
    )
    reolink_entry.add_to_hass(hass)

    entry = MockConfigEntry(domain=DOMAIN, title="Reolink Talk", data={}, options={})
    entry.add_to_hass(hass)

    # reolink_talk depends on the core "reolink" integration; keep it offline.
    with (
        patch("homeassistant.components.reolink.async_setup_entry", AsyncMock(return_value=True)),
        patch("homeassistant.components.reolink.async_unload_entry", AsyncMock(return_value=True)),
        patch("homeassistant.components.reolink.async_migrate_entry", AsyncMock(return_value=True), create=True),
        patch(
            "custom_components.reolink_talk.media_player.ReolinkTalkPlayer._probe_ability",
            AsyncMock(return_value=ABILITY),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry
        # Unload while the reolink patches are still active, otherwise the
        # harness teardown runs the real reolink unload against the mock entry.
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.config_entries.async_unload(reolink_entry.entry_id)
        await hass.async_block_till_done()


async def test_entity_created_with_expected_features(hass: HomeAssistant, setup_integration):
    state = hass.states.get(ENTITY_ID)
    assert state is not None, "media_player entity was not created"
    assert state.state == "idle"
    assert state.attributes["supported_features"] == EXPECTED_FEATURES
    assert state.attributes["device_class"] == "speaker"


async def test_card_controls_are_accepted_by_ha(hass: HomeAssistant, setup_integration):
    """Cards call media_play_pause unconditionally; HA accepts it only with PLAY and PAUSE."""
    for service in ("media_play_pause", "media_play", "media_stop", "media_pause"):
        await hass.services.async_call(MP_DOMAIN, service, {"entity_id": ENTITY_ID}, blocking=True)
    assert hass.states.get(ENTITY_ID).state == "idle"


async def test_options_flow_opens(hass: HomeAssistant, setup_integration):
    """OptionsFlow without a config_entry constructor argument (HA >= 2024.11 pattern)."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_no_ha_deprecation_warnings(hass: HomeAssistant, setup_integration, caplog):
    """HA reports deprecated API usage through warnings naming the integration."""
    markers = ("deprecat", "will stop working", "detected that custom integration")
    offenders = [
        rec.getMessage()
        for rec in (*caplog.get_records("setup"), *caplog.records)
        if rec.levelno >= logging.WARNING
        and "reolink_talk" in rec.getMessage()
        and any(m in rec.getMessage().lower() for m in markers)
    ]
    assert not offenders, "\n".join(offenders)
