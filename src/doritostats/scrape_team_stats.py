import numpy as np
import pandas as pd
from espn_api.football import League, Team, Player, Matchup
from typing import Optional, List, Tuple, Dict
from src.doritostats.fetch_utils import fetch_league
from src.doritostats.PseudoMatchup import PseudoMatchup
from src.doritostats.analytic_utils import (
    get_weekly_finish,
    get_lineup_efficiency,
    get_best_trio,
    sum_bench_points,
    get_score_surprise,
    get_top_players,
    avg_slot_score,
)
from src.doritostats.luck_index import get_weekly_luck_index


def is_playoff_game(league: League, matchup: Matchup, week: int) -> bool:
    """Accepts a League and Matchup object and determines if the matchup was a playoff game"""

    # False if not playoff time yet
    if week <= league.settings.reg_season_count:
        return False

    # False if a team is on Bye
    if not matchup.away_team:
        return False

    # False if it is a team that did not make the playoffs
    elif matchup.home_team.standing > league.settings.playoff_team_count:
        return False

    # Is it at least 1 week after playoffs began?
    elif (week - 1) > league.settings.reg_season_count:
        # Check if team has already lost a playoff game
        for wk in range(league.settings.reg_season_count + 1, week):
            if matchup.away_team.outcomes[wk - 1] == "L":
                return False

        last_week_score = matchup.away_team.scores[week - 2]
        last_week_opp_score = matchup.away_team.schedule[week - 2].scores[week - 2]

        # True if team won last week
        if last_week_score > last_week_opp_score:
            return True

        # True if team won last week on a tiebreaker
        elif (last_week_score == last_week_opp_score) and (
            matchup.away_team.points_for
            > matchup.away_team.schedule[week - 2].points_for
        ):
            return True

        # False if team lost last week
        else:
            return False

    # True if it is the first week of the playoffs
    else:
        return True


def get_stats_by_week(
    league_id: int, year: int, swid: str, espn_s2: str
) -> pd.DataFrame:
    """This function creates a historical dataframe for the league in a given year.

    It generates this dataframe by:
        - For each team in League.teams:
            - For each week in league.settings.matchup_periods:
                Manually grab each stat by looking at the Team and the Team's opponent.

    This is used for years prior to 2019, when BoxScores are unavailable.

    Args:
        league_id (int): League ID
        year (int): Year of the league
        swid (str): User credential
        espn_s2 (str): User credential

    Returns:
        pd.DataFrame: Historical stats dataframe
    """

    # Fetch league for year
    league = fetch_league(league_id=league_id, year=year, swid=swid, espn_s2=espn_s2)

    # Instantiate data frame
    df = pd.DataFrame()

    # Loop through every game in the team's schedule
    for week in range(
        min(len(league.settings.matchup_periods), league.currentMatchupPeriod)
    ):
        # Instantiate week data frame
        df_week = pd.DataFrame()

        # Loop through every team
        for i, team in enumerate(league.teams):
            # Skip byes
            if team.schedule[i] == team:
                continue

            # Add observation for home team
            df_week.loc[i, "year"] = year
            df_week.loc[i, "week"] = week + 1
            df_week.loc[i, "location"] = "unknown"
            df_week.loc[i, "team_owner"] = team.owner
            df_week.loc[i, "team_name"] = team.team_name
            df_week.loc[i, "team_division"] = team.division_name
            df_week.loc[i, "team_score"] = team.scores[week]

            df_week.loc[i, "opp_owner"] = team.schedule[week].owner
            df_week.loc[i, "opp_name"] = team.schedule[week].team_name
            df_week.loc[i, "opp_division"] = team.schedule[week].division_name
            df_week.loc[i, "opp_score"] = team.schedule[week].scores[week]

            # Is the game in the regular season?
            df_week.loc[i, "is_regular_season"] = (
                week < league.settings.reg_season_count
            )

            # Is the game a playoff game? (not including consolation)
            # Home team is the lower seed
            matchup_teams = sorted(
                [team, team.schedule[week]], key=lambda x: x.standing
            )
            matchup = PseudoMatchup(matchup_teams[0], matchup_teams[1])
            df_week.loc[i, "is_playoff"] = is_playoff_game(league, matchup, week + 1)

        df = pd.concat([df, df_week])

    # Calculated fields
    df["score_dif"] = df["team_score"] - df["opp_score"]

    # Calculated fields
    def calculate_outcome(s):
        if s.score_dif > 0:
            return "win"
        elif s.score_dif < 0:
            return "lose"
        else:
            return "tie"

    df["outcome"] = df.apply(calculate_outcome, axis=1)
    df["is_meaningful_game"] = df.is_regular_season | df.is_playoff

    # More calculated fields
    df.sort_values(["team_owner", "week"], inplace=True)
    df["win"] = df.outcome == "win"
    df["tie"] = df.outcome == "tie"
    df["lose"] = df.outcome == "lose"
    df["season_wins"] = df.groupby(["team_owner"]).win.cumsum()
    df["season_ties"] = df.groupby(["team_owner"]).tie.cumsum()
    df["season_losses"] = df.groupby(["team_owner"]).lose.cumsum()
    df["win_pct"] = df.season_wins / df[["season_wins", "season_losses"]].sum(axis=1)
    df["win_pct_entering_matchup"] = (
        df.groupby(["team_owner"])["win_pct"].apply(lambda x: x.shift(1)).values
    )

    return df


def get_stats_by_matchup(
    league_id: int, year: int, swid: str, espn_s2: str
) -> pd.DataFrame:
    """This function creates a historical dataframe for the league in a given year.

    It generates this dataframe by:
        - For each week that has elapsed, get the BoxScores for that week:
            - For each Matchup in the BoxScores:
                Grab each stat by looking at the Matchup.home_team, Matchup.home_lineup, Matchup.away_team, and Matchup.away_lineup

    This is used for years in 2019 or later, where the BoxScores are available.

    Args:
        league_id (int): League ID
        year (int): Year of the league
        swid (str): User credential
        espn_s2 (str): User credential

    Returns:
        pd.DataFrame: Historical stats dataframe
    """
    # Fetch league for year
    league = fetch_league(league_id=league_id, year=year, swid=swid, espn_s2=espn_s2)

    # Instantiate data frame
    df = pd.DataFrame()

    # Loop through each week that has happened
    current_matchup_period = league.settings.week_to_matchup_period[league.current_week]
    for week in range(current_matchup_period):
        box_scores = league.box_scores(week + 1)

        # Instantiate week data frame
        df_week = pd.DataFrame()
        for i, matchup in enumerate(box_scores):
            # Skip byes
            if (type(matchup.home_team) != Team) or (type(matchup.away_team) != Team):
                continue

            # Add observation for home team
            df_week.loc[i * 2, "year"] = year
            df_week.loc[i * 2, "week"] = week + 1
            df_week.loc[i * 2, "location"] = "HOME"
            df_week.loc[i * 2, "team_owner"] = matchup.home_team.owner
            df_week.loc[i * 2, "team_name"] = matchup.home_team.team_name
            df_week.loc[i * 2, "team_division"] = matchup.home_team.division_name
            df_week.loc[i * 2, "team_score"] = matchup.home_score
            df_week.loc[i * 2, "opp_owner"] = matchup.away_team.owner
            df_week.loc[i * 2, "opp_name"] = matchup.away_team.team_name
            df_week.loc[i * 2, "opp_division"] = matchup.away_team.division_name
            df_week.loc[i * 2, "opp_score"] = matchup.away_score
            df_week.loc[i * 2, "is_regular_season"] = (
                week < league.settings.reg_season_count
            )
            df_week.loc[i * 2, "is_playoff"] = is_playoff_game(
                league, matchup, week + 1
            )

            home_lineup = matchup.home_lineup
            df_week.loc[i * 2, "weekly_finish"] = get_weekly_finish(
                league, matchup.home_team, week + 1
            )
            df_week.loc[i * 2, "lineup_efficiency"] = get_lineup_efficiency(
                league, home_lineup
            )
            df_week.loc[i * 2, "best_trio"] = get_best_trio(league, home_lineup)
            df_week.loc[i * 2, "bench_points"] = sum_bench_points(league, home_lineup)
            df_week.loc[i * 2, "team_projection_beat"] = get_score_surprise(
                league, home_lineup
            )

            for slot in ["QB", "RB", "WR", "TE", "RB/WR/TE", "D/ST", "K"]:
                df_week.loc[
                    i * 2, "{}_pts".format(slot.replace("/", "_"))
                ] = avg_slot_score(league, home_lineup, slot=slot)

                # Get the best player for each slot
                top_players = get_top_players(home_lineup, slot, 1)
                if not top_players:
                    # If no player for this position is rostered
                    df_week.loc[i * 2, "best_{}".format(slot.replace("/", "_"))] = 0
                else:
                    df_week.loc[
                        i * 2, "best_{}".format(slot.replace("/", "_"))
                    ] = top_players[0].points
                try:
                    df_week.loc[
                        i * 2, "worst_{}".format(slot.replace("/", "_"))
                    ] = np.min(
                        [
                            player.points
                            for player in get_top_players(home_lineup, slot, 10)
                            if player.slot_position not in ("BE", "IR")
                        ]
                    )
                except Exception:
                    df_week.loc[i * 2, "worst_{}".format(slot.replace("/", "_"))] = 0

            # Add observation for away team
            df_week.loc[i * 2 + 1, "year"] = year
            df_week.loc[i * 2 + 1, "week"] = week + 1
            df_week.loc[i * 2 + 1, "location"] = "AWAY"
            df_week.loc[i * 2 + 1, "team_owner"] = matchup.away_team.owner
            df_week.loc[i * 2 + 1, "team_name"] = matchup.away_team.team_name
            df_week.loc[i * 2 + 1, "team_division"] = matchup.away_team.division_name
            df_week.loc[i * 2 + 1, "team_score"] = matchup.away_score
            df_week.loc[i * 2 + 1, "opp_owner"] = matchup.home_team.owner
            df_week.loc[i * 2 + 1, "opp_name"] = matchup.home_team.team_name
            df_week.loc[i * 2 + 1, "opp_division"] = matchup.home_team.division_name
            df_week.loc[i * 2 + 1, "opp_score"] = matchup.home_score
            df_week.loc[i * 2 + 1, "is_regular_season"] = (
                week < league.settings.reg_season_count
            )
            df_week.loc[i * 2 + 1, "is_playoff"] = is_playoff_game(
                league, matchup, week + 1
            )

            away_lineup = matchup.away_lineup
            df_week.loc[i * 2 + 1, "weekly_finish"] = get_weekly_finish(
                league, matchup.away_team, week + 1
            )
            df_week.loc[i * 2 + 1, "lineup_efficiency"] = get_lineup_efficiency(
                league, away_lineup
            )
            df_week.loc[i * 2 + 1, "best_trio"] = get_best_trio(league, away_lineup)
            df_week.loc[i * 2 + 1, "bench_points"] = sum_bench_points(
                league, away_lineup
            )
            df_week.loc[i * 2 + 1, "team_projection_beat"] = get_score_surprise(
                league, away_lineup
            )
            for slot in ["QB", "RB", "WR", "TE", "RB/WR/TE", "D/ST", "K"]:
                df_week.loc[
                    i * 2 + 1, "{}_pts".format(slot.replace("/", "_"))
                ] = avg_slot_score(league, away_lineup, slot=slot)

                # Get the best player for each slot
                top_players = get_top_players(away_lineup, slot, 1)
                if not top_players:
                    # If no player for this position is rostered
                    df_week.loc[i * 2 + 1, "best_{}".format(slot.replace("/", "_"))] = 0
                else:
                    df_week.loc[
                        i * 2 + 1, "best_{}".format(slot.replace("/", "_"))
                    ] = top_players[0].points
            #                 df_week.loc[i*2+1, 'worst_{}'.format(slot.replace('/', '_'))] = np.min([player.points for player in get_top_players(home_lineup, slot, 10) if player.slot_position not in ('BE', 'IR')])

            #         df_week.loc[i*2, 'team_record'] = "{}-{}-{}".format(matchup.home_team.wins, matchup.home_team.losses, matchup.home_team.ties)
            #         df_week.loc[i*2, 'team_season_points_for'] = matchup.home_team.points_for
            #         df_week.loc[i*2, 'team_season_standing'] = matchup.home_team.standing
            #         df_week.loc[i*2, 'team_season_streak'] = "{}-{}".format(matchup.home_team.streak_type, matchup.home_team.streak_length)
            #         df_week.loc[i*2, 'team_projected'] = matchup.home_projected

        # Concatenate week's data
        df = pd.concat([df, df_week])

    # Calculated fields
    df["score_dif"] = df["team_score"] - df["opp_score"]
    df["team_projection"] = df["team_score"] - df["team_projection_beat"]

    # Calculated fields
    def calculate_outcome(s):
        if s.score_dif > 0:
            return "win"
        elif s.score_dif < 0:
            return "lose"
        else:
            return "tie"

    df["outcome"] = df.apply(calculate_outcome, axis=1)
    df["is_meaningful_game"] = df.is_regular_season | df.is_playoff

    # More calculated fields
    df.sort_values(["team_owner", "week"], inplace=True)
    df["win"] = df.outcome == "win"
    df["tie"] = df.outcome == "tie"
    df["lose"] = df.outcome == "lose"
    df["season_wins"] = df.groupby(["team_owner"]).win.cumsum()
    df["season_ties"] = df.groupby(["team_owner"]).tie.cumsum()
    df["season_losses"] = df.groupby(["team_owner"]).lose.cumsum()
    df["win_pct"] = df.season_wins / df[["season_wins", "season_losses"]].sum(axis=1)
    df["win_pct_entering_matchup"] = (
        df.groupby(["team_owner"])["win_pct"].apply(lambda x: x.shift(1)).values
    )

    return df


def append_streaks(df: pd.DataFrame) -> pd.DataFrame:
    """Add the win streak for a team to the Historical stats dataframe

    Args:
        df (pd.DataFrame): Historical stats

    Returns:
        pd.DataFrame: Historical stats with `streaks` column appended
    """
    df = df.sort_values(["team_owner", "year", "week"])

    streaks = [1 if df.score_dif.tolist()[0] > 0 else -1]
    for i in range(1, len(df)):
        # New team: did the team win or lose their first game? (ties handled at the end)
        if df.team_owner.tolist()[i] != df.team_owner.tolist()[i - 1]:
            streaks.append(1 if df.score_dif.tolist()[i] > 0 else -1)

        # COMMENT OUT IF YOU WANT WIN STREAKS TO ROLL INTO THE NEXT SEASON
        # New year
        elif df.year.tolist()[i] != df.year.tolist()[i - 1]:
            streaks.append(1 if df.score_dif.tolist()[i] > 0 else -1)

        # Begin new streak: won this week, lost/tie last week
        elif (df.score_dif.tolist()[i] > 0) and (df.score_dif.tolist()[i - 1] <= 0):
            streaks.append(1)

        # Add to win streak: won this week, won last week
        elif df.score_dif.tolist()[i] > 0:
            streaks.append(streaks[-1] + 1)

        # Begin losing streak: lost this week, won/tie last week
        elif (df.score_dif.tolist()[i] < 0) and (df.score_dif.tolist()[i - 1] >= 0):
            streaks.append(-1)

        # Add to losing streak: lost this week, lost last week
        elif df.score_dif.tolist()[i] < 0:
            streaks.append(streaks[-1] - 1)

        # Tie
        elif df.score_dif.tolist()[i] == 0:
            streaks.append(0)

        else:
            streaks.append("error")  # type: ignore

    df["streak"] = streaks
    return df


def scrape_team_stats(
    league_id: int,
    start_year: int,
    end_year: int,
    swid: str,
    espn_s2: str,
    df_prev: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Generate a table with weekly matchup statistics for every owner and every week over multiple years.

    Args:
        league_id (int): League ID
        start_year (int): Oldest year to get data from
        end_year (int): Most recent year to get data from
        swid (str): ESPN SWID credential
        espn_s2 (str): ESPN_S2 credential
        df_prev (pd.DataFrame, optional): Historical stats dataframe to append to. Defaults to None.

    Returns:
        pandas dataframe: Weekly historical stats for the given league
    """
    if df_prev is None:
        df = pd.DataFrame()
    else:
        df = df_prev

    # Fetch data for each year and append it to the dataframe
    for year in range(start_year, end_year + 1):
        print("\n[BUILDING LEAGUE] Fetching historical stats for {}...".format(year))
        if year < 2019:
            # BoxScore information is not available for years prior to 2019
            # Build the data from Team information
            df_year = get_stats_by_week(league_id, year, swid, espn_s2)
            df_year["box_score_available"] = False
        else:
            # Build the data from BoxScore information
            df_year = get_stats_by_matchup(league_id, year, swid, espn_s2)
            df_year["box_score_available"] = True

        # Properly cast boolean columns to bool
        bool_cols = {
            col: bool for col in df_year.columns[df_year.columns.str.contains("is_")]
        }
        df_year = df_year.astype(bool_cols)

        # Concatenate week's data
        df = pd.concat([df, df_year])

    # Get adjusted score
    # The score multiplier is defined as the median score of the league in a given year
    # divided by the median score of the league in the most recent completed year.
    year_multiplier_map = (
        df[df.is_meaningful_game][["year", "team_score"]]
        .groupby("year")
        .median()
        .team_score
        / df[(df.is_meaningful_game) & (df.year == end_year - 1)].team_score.median()
    ).to_dict()

    def get_adjusted_score(s):
        return s.team_score / year_multiplier_map[s.year]

    def get_opp_adjusted_score(s):
        return s.opp_score / year_multiplier_map[s.year]

    df["team_score_adj"] = df.apply(get_adjusted_score, axis=1)
    df["opp_score_adj"] = df.apply(get_opp_adjusted_score, axis=1)

    # Correct capitalization of team owners
    df["team_owner"] = df.team_owner.str.title()

    # Map owners of previous/co-owned teams to current owners to preserve "franchise"
    owner_map = {"Katie Brooks": "Nikki Pilla"}
    df.replace({"team_owner": owner_map, "opp_owner": owner_map}, inplace=True)

    # Get win streak data for each owner
    df = append_streaks(df)

    return df


def update_current_season_stats(
    league_id: int,
    df: Optional[pd.DataFrame] = None,
    file_path: Optional[str] = None,
    swid: Optional[str] = None,
    espn_s2: Optional[str] = None,
):
    """Update the current season of the historical stats dataframe.
    Note: the entire season must be overwritten because the adjusted stats will change for all weeks.

    Args:
        league_id (int): the league id
        df (pd.Dataframe, optional): the historical stats dataframe to add to (if no file path is passed in)
        file_path (str): the file path to the historical stats dataframe (if no df is passed in)
        swid (str, optional): The SWID to access the league (for private leagues). Defaults to None.
        espn_s2 (str, optional): The ESPN_S2 to access the league (for private leagues). Defaults to None.

    Returns:
        pd.DataFrame: The updated historical stats dataframe
    """
    # If no dataframe is passed in, read the dataframe from the file path
    if df is None:
        if file_path is None:
            raise ValueError("Must pass in a dataframe or file path")
        else:
            df = pd.read_csv(file_path)

    # Identify the current season
    cur_season = df.year.max().astype(int)

    # Keep data from previous seasons
    df_prev_season = df[df.year != cur_season]

    # Re-build the dataframe for the current season
    return scrape_team_stats(
        league_id, cur_season, cur_season, swid, espn_s2, df_prev=df_prev_season
    )


def add_newest_season_to_stats(
    league_id: int,
    df: Optional[pd.DataFrame] = None,
    file_path: Optional[str] = None,
    swid: Optional[str] = None,
    espn_s2: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Add the newest year to the historical stats dataframe.

    Args:
        league_id (int): the league id
        df (pd.Dataframe, optional): the historical stats dataframe to add to (if no file path is passed in)
        file_path (str): the file path to the historical stats dataframe (if no df is passed in)
        swid (str, optional): The SWID to access the league (for private leagues). Defaults to None.
        espn_s2 (str, optional): The ESPN_S2 to access the league (for private leagues). Defaults to None.

    Returns:
        pd.DataFrame: The updated historical stats dataframe
    """
    # If no dataframe is passed in, read the dataframe from the file path
    if df is None:
        if file_path is None:
            raise ValueError("Must pass in a dataframe or file path")
        else:
            df = pd.read_csv(file_path)

    # Identify the current season
    new_season = df.year.max().astype(int) + 1

    # Keep data from previous seasons
    max_week_in_last_season = df[df.year == new_season - 1].week.max()
    if max_week_in_last_season < 14:
        # Prompt the user if they want to update the historical stats
        if (
            input(
                "The {} season only has data through Week {}. Are you sure you want to fetch data for {}? (y/N)".format(
                    new_season - 1, max_week_in_last_season, new_season
                )
            )
            != "y"
        ):
            if (
                input(
                    "Would you like to update the {} season instead? (y/N)".format(
                        new_season - 1
                    )
                )
                == "y"
            ):
                return update_current_season_stats(
                    df=df,
                    league_id=league_id,
                    swid=swid,
                    espn_s2=espn_s2,
                )
            else:
                print("Exiting process without updating the dataframe.")

    # Re-build the dataframe for the new season
    return scrape_team_stats(
        league_id, new_season, new_season, swid, espn_s2, df_prev=df
    )
