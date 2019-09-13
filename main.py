from league import League
from authorize import Authorize
from team import Team
from player import Player

import requests
from tabulate import tabulate as table


username = 'desidezdez@gmail.com'
password = None;        
league_id = 1086064
espnAuth = '55B70875-0A4B-428F-B708-750A4BB28FA1'
espn_s2 = 'AEA2XITlUD5oV4FaNBbJ6vSaLZUJirSQoy7n9no%2BYrf0pEVcWac3tRNuqm2%2FoAH%2FuHCdPU1iiz%2Ba4ja%2Brv544LEZ859FGbTRnonPa8zbSDV6gCBaUahVbtfQCVoeL14qyK%2BNhb%2FqtRqVaL2r6jpKTUXEjzGBOHcBeo2s5a3PL7YmPM88ro73Usq4IGM%2BZf%2Fszl%2Fh%2FJatefzg4YJLzhG5dWT1HT23SRuMcTMT18so7WlqP%2F6oz%2FGCcz4tTzb1Xa02TvTeRF%2FcKUGbq%2FfY0JTSClDc'      

def getUrl(year, league_id):
    url = ''
    if (year >= 2019):         # ESPN API v3
        url = "https://fantasy.espn.com/apis/v3/games/ffl/seasons/" + \
            str(year) + "/segments/0/leagues/" + str(league_id)
    else:                      # ESPN API v2
        url = "https://fantasy.espn.com/apis/v3/games/ffl/leagueHistory/" + \
            str(league_id) + "?seasonId=" + str(year)
    return url
        
matt_league_id_1 = 640928
matt_league_id_2 = 293050

year = 2019
matt_cookies = {'swid' : matt_client.swid, 'espn_s2' : matt_client.espn_s2};
url = getUrl(year, matt_league_id_1)



if False:
    #matchups = requests.get(url, cookies = matt_cookies, params = {'view' : 'mMatchup'}).json()
    teams = requests.get(url, cookies = matt_cookies, params = {'view' : 'mTeam'}).json()
    #rosters = requests.get(url, cookies = matt_cookies, params = {'view' : 'mRoster'}).json()
    #settings = requests.get(url, cookies = matt_cookies, params = {'view' : 'mSettings'}).json()
    # kona = requests.get(url, cookies = auth, params = {'view' : 'kona_player_info'}).json()
    player_wl = requests.get(url, cookies = matt_cookies, params = {'view' : 'player_wl'}).json()
    # schedule = requests.get(url, cookies = auth, params = {'view' : 'mSchedule'}).json()
    # team = teams['teams'][0]


if True:
    leg = League(league_id, 2019, espnAuth, espn_s2)
    print(leg)

if False:
    leg = League(league_id, 2018)
    print(leg)

if False:
    leg = League(matt_league_id_1, 2019, matt_client.swid, matt_client.espn_s2)

if False:
    t = leg.teams[1]
    p =t.rosters[1][0]
    week = 1


