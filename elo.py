from dataclasses import dataclass


@dataclass(frozen=True)
class Rank:
    name: str
    minimum: int


RANKS = (
    Rank("IRON", 0),
    Rank("BRONZE", 800),
    Rank("SILVER", 1000),
    Rank("GOLD", 1200),
    Rank("PLATINUM", 1400),
    Rank("DIAMOND", 1600),
    Rank("MASTER", 1800),
    Rank("ELITE", 2000),
)


def get_rank(elo: int) -> str:
    current = RANKS[0]
    for rank in RANKS:
        if elo >= rank.minimum:
            current = rank
        else:
            break
    return current.name


def expected_score(player_elo: float, opponent_elo: float) -> float:
    return 1 / (1 + 10 ** ((opponent_elo - player_elo) / 400))


def calculate_elo(player_elo: int, opponent_elo: int, won: bool, k_factor: int = 32) -> int:
    expected = expected_score(player_elo, opponent_elo)
    actual = 1.0 if won else 0.0
    change = round(k_factor * (actual - expected))
    return max(-player_elo, change)
