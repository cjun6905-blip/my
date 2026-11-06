from dataclasses import dataclass


@dataclass
class GenerationConfig:
    temperature: float = 0.8
    max_output_tokens: int = 1000


@dataclass
class GenerationResult:
    content: str
    model_used: str
    sources: tuple = ()
    web_attempted: bool = False
