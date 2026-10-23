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
    import autoexpress_core
except ImportError:  # running from a symlink into the repository
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import autoexpress_core


@invocation_output("autoexpress_expression_prompts_output")
class AutoExpressExpressionPromptsOutput(BaseInvocationOutput):
    prompts: list[str] = OutputField(description="One prompt per expression")
    names: list[str] = OutputField(description="Expression names, in the same order as the prompts")


@invocation(
    "autoexpress_expression_prompts",
    title="AutoExpress Expression Prompts",
    tags=["prompt", "expression", "autoexpress", "character"],
    category="prompt",
    version="1.0.0",
)
class AutoExpressExpressionPromptsInvocation(BaseInvocation):
    """Builds AutoExpress expression prompts. Iterate over the prompts to inpaint the face once per expression."""

    flavor: Literal["anime", "realistic", "illustrious"] = InputField(
        default=autoexpress_core.DEFAULT_FLAVOR, description="Prompt style: anime tags or natural language"
    )
    base_prompt: str = InputField(
        default="", description="Character prompt placed before every expression", ui_component=UIComponent.Textarea
    )
    expressions: str = InputField(
        default="all", description="'all', or a comma separated list such as: joy, anger, surprise"
    )

    def invoke(self, context: InvocationContext) -> AutoExpressExpressionPromptsOutput:
        names = [name.strip().lower() for name in self.expressions.split(",") if name.strip()]
        only = None if not names or names == ["all"] else names
        selected = autoexpress_core.get_expressions(self.flavor, only)
        return AutoExpressExpressionPromptsOutput(
            prompts=[autoexpress_core.join_prompt(self.base_prompt, tags) for tags in selected.values()],
            names=list(selected),
        )
