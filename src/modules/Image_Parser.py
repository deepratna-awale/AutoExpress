# Read Image Data using sd_parsers
from sd_parsers import ParserManager

parser_manager = ParserManager()
prompt_info = parser_manager.parse("00003-1286526087.png")

if prompt_info:
    for prompt in prompt_info.prompts:
        print(f"Prompt: {prompt.value}")