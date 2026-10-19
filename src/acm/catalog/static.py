"""Build runtime providers from ``config.yaml`` entries."""

from acm.catalog.model import ModelCard, Provider
from acm.config.refs import parse_credential
from acm.config.schema import ProviderConfig


def static_provider(name: str, cfg: ProviderConfig) -> Provider:
    assert cfg.protocol is not None and cfg.base_url is not None
    cards = tuple(
        ModelCard(
            provider=name,
            id=mid,
            protocols=(cfg.protocol,),
            roles=tuple(spec.roles),
            context=spec.context_window,
            output=spec.max_output_tokens,
            input=tuple(spec.input) or ("text",),
            tool_call=spec.tool_call,
            reasoning=spec.reasoning,
            effort=spec.effort,
        )
        for mid, spec in cfg.models.items()
    )
    return Provider(
        name=name,
        endpoints={cfg.protocol: cfg.base_url},
        credential=parse_credential(cfg.api_key),
        cards=cards,
        headers=dict(cfg.headers),
        origin="static",
    )
