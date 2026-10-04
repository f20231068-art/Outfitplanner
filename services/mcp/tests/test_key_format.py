"""A key pasted into a host's variables screen can arrive on one line with \\n markers, or wrapped in quote
marks. Every one of those spellings must load, or the server crashes at start-up."""

import pytest

from mcp_server.auth import ServiceJWTVerifier
from mcp_server.config import Settings
from tests.keys import PUBLIC_PEM


@pytest.mark.parametrize("wrap", ["{}", '"{}"', "'{}'", ' "{}" '])
def test_public_key_loads_in_every_spelling(wrap):
    one_line = PUBLIC_PEM.strip().replace("\n", "\\n")
    cfg = Settings(mcp_jwt_public_key=wrap.format(one_line), _env_file=None)
    ServiceJWTVerifier(cfg.jwt_public_key_pem, cfg.mcp_jwt_issuer, cfg.mcp_jwt_audience)  # raises if unreadable
