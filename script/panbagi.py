import enum
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_RE_TEMPLATE_VAR = re.compile(r"{{(.*?)}}")


class FragmentType(enum.Enum):
    Str = enum.auto()
    Var = enum.auto()


@dataclass
class Fragment:
    fragment_type: FragmentType
    value: str


def _construct_template(tpl_str: str) -> Iterator[Fragment]:
    cursor: int = 0
    for matched in _RE_TEMPLATE_VAR.finditer(tpl_str):
        var_name = matched.groups()[0]

        start_pos = matched.start()
        if cursor < start_pos:
            yield Fragment(FragmentType.Str, tpl_str[cursor:start_pos])
        yield Fragment(FragmentType.Var, var_name)
        cursor = matched.end()

    if last_piece := tpl_str[cursor:]:
        yield Fragment(FragmentType.Str, last_piece)


@dataclass
class Template:
    fragments: list[Fragment]

    @classmethod
    def load(cls, path: str):
        raw_template = Path(path).read_text()
        return cls.parse(raw_template)

    @classmethod
    def parse(cls, raw_text: str):
        fragments = _construct_template(raw_text)
        return cls(list(fragments))

    def render_iter(self, vars: dict[str, str]) -> Iterator[str]:
        for fragment in self.fragments:
            match fragment.fragment_type:
                case FragmentType.Str:
                    yield fragment.value
                case FragmentType.Var:
                    yield vars[fragment.value]

    def render(self, vars: dict[str, str]) -> str:
        return "".join(self.render_iter(vars))
