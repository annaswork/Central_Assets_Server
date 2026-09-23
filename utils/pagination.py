"""Pagination math and parameter handling."""

from dataclasses import dataclass

from config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        p = max(1, self.page)
        ps = min(MAX_PAGE_SIZE, max(1, self.page_size))
        object.__setattr__(self, "page", p)
        object.__setattr__(self, "page_size", ps)

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
