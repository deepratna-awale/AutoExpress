import sys
from pathlib import Path
from typing import Literal

from invokeai.invocation_api import (
    BaseInvocation,
    BaseInvocationOutput,
    InputField,
    InvocationContext,
    OutputField,
    UIComponent,
    invocation,
    invocation_output,
)

try:
    import emotica_core
except ImportError:  # running from a symlink into the repository
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import emotica_core


@invocation_output("emotica_expression_prompts_output")
class EmoticaExpressionPromptsOutput(BaseInvocationOutput):
    prompts: list[str] = OutputField(description="One prompt per expression")
    names: list[str] = OutputField(description="Expression names, in the same order as the prompts")
    negative: str = OutputField(description="Negative prompt with the family's negative tags added")


@invocation(
    "emotica_expression_prompts",
    title="Emotica Expression Prompts",
    tags=["prompt", "expression", "emotica", "character"],
    category="prompt",
    version="1.1.0",
)
class EmoticaExpressionPromptsInvocation(BaseInvocation):
    """Builds Emotica expression prompts. Iterate over the prompts to inpaint the face once per expression."""

    prompt_style: Literal["auto", "danbooru", "e621", "pony", "illustrious", "sdxl_base", "natural_language"] = InputField(
        default="auto", description="Model family the prompts are written for. 'auto' picks it from the checkpoint name"
    )
    checkpoint_name: str = InputField(default="", description="Main model name, used when the prompt style is 'auto'")
    base_prompt: str = InputField(
        default="", description="Character prompt placed before every expression", ui_component=UIComponent.Textarea
    )
    base_negative: str = InputField(default="", description="Negative prompt", ui_component=UIComponent.Textarea)
    expressions: str = InputField(
        default="all", description="'all', or a comma separated list such as: joy, anger, surprise"
    )

    def invoke(self, context: InvocationContext) -> EmoticaExpressionPromptsOutput:
        sets = emotica_core.expression_sets
        family = emotica_core.resolve_flavor(self.prompt_style, self.checkpoint_name)
        wanted = [name.strip().lower() for name in self.expressions.split(",") if name.strip()]
        only = None if not wanted or wanted == ["all"] else wanted
        names = list(emotica_core.get_expressions(family, only))
        return EmoticaExpressionPromptsOutput(
            prompts=[sets.build_prompt(self.base_prompt, name, family) for name in names],
            names=names,
            negative=sets.build_negative(self.base_negative, family),
        )


@invocation(
    "autoexpress_expression_prompts",
    title="Emotica Expression Prompts (old name)",
    tags=["prompt", "expression", "emotica", "character"],
    category="prompt",
    version="1.1.0",
)
class AutoExpressExpressionPromptsInvocation(EmoticaExpressionPromptsInvocation):
    """The node under its former id, so workflows saved before the rename still load."""
