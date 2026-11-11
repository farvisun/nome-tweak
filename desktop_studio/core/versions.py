"""Strict SemVer comparison for published application releases."""
from dataclasses import dataclass
from functools import total_ordering
import re


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    major: int
    minor: int
    patch: int
    prerelease: tuple = ()
    build: str = ""

    @classmethod
    def parse(cls, text):
        if not isinstance(text, str) or len(text) > 150:
            raise ValueError("Release version must be a semantic version such as v1.2.3")
        match = re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?", text)
        if not match:
            raise ValueError("Release version must be a semantic version such as v1.2.3")
        major, minor, patch, pre, build = match.groups()
        prerelease = tuple(pre.split(".")) if pre else ()
        if any(not item or (item.isdigit() and len(item) > 1 and item.startswith("0")) for item in prerelease) or (build and any(not item for item in build.split("."))):
            raise ValueError("Invalid semantic version identifiers")
        return cls(int(major), int(minor), int(patch), prerelease, build or "")

    def __str__(self):
        return f"{self.major}.{self.minor}.{self.patch}" + ("-" + ".".join(self.prerelease) if self.prerelease else "") + ("+" + self.build if self.build else "")

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease) == (other.major, other.minor, other.patch, other.prerelease)

    def __hash__(self):
        return hash((self.major, self.minor, self.patch, self.prerelease))

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        left, right = (self.major, self.minor, self.patch), (other.major, other.minor, other.patch)
        if left != right:
            return left < right
        if not self.prerelease or not other.prerelease:
            return bool(self.prerelease) and not other.prerelease
        for a, b in zip(self.prerelease, other.prerelease):
            if a == b:
                continue
            if a.isdigit() and b.isdigit():
                return int(a) < int(b)
            if a.isdigit() != b.isdigit():
                return a.isdigit()
            return a < b
        return len(self.prerelease) < len(other.prerelease)
