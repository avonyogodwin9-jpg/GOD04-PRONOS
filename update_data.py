#!/usr/bin/env python3
"""Fetches football-data.org fixtures and standings, then writes static JSON for GitHub Pages."""
import os, json, math, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

TOKEN=os.environ.get("FOOTBALL_DATA_TOKEN","").strip()
if not TOKEN:
    raise SystemExit("Missing FOOTBALL_DATA_TOKEN secret")
BASE="https://api.football-data.org/v4"
# Free access differs by account. The workflow gracefully skips inaccessible standings.
COMPETITIONS=["PL","PD","BL1","SA","FL1","CL"]
today=datetime.now(timezone.utc).date()
date_from=(today-timedelta(days=3)).isoformat()
date_to=(today+timedelta(days=7)).isoformat()

def get(path):
    req=urllib.request.Request(BASE+path,headers={"X-Auth-Token":TOKEN,"User-Agent":"GOD04-PRONOS/1.0"})
    with urllib.request.urlopen(req,timeout=25) as response:
        return json.load(response)

def poisson(lam,k):
    return math.exp(-lam)*(lam**k)/math.factorial(k)

def main():
    # One fixture request for all competitions, within the provider's free request limits.
    try:
        payload=get(f"/matches?dateFrom={date_from}&dateTo={date_to}")
        matches=payload.get("matches",[])
    except Exception as e:
        raise SystemExit(f"Could not retrieve matches: {e}")

    standings={}
    errors=[]
    for code in COMPETITIONS:
        try:
            data=get(f"/competitions/{code}/standings")
            rows=[]
            for block in data.get("standings",[]):
                if block.get("type")=="TOTAL":
                    rows=block.get("table",[])
                    break
            if rows:
                standings[code]={str(r["team"]["id"]):r for r in rows if r.get("playedGames",0)>0}
        except Exception as e:
            errors.append(f"{code}: {e}")

    out=[]
    for m in matches:
        comp=m.get("competition",{}).get("code","")
        home=m.get("homeTeam",{}); away=m.get("awayTeam",{})
        hname=home.get("name","Équipe domicile"); aname=away.get("name","Équipe extérieure")
        hrow=standings.get(comp,{}).get(str(home.get("id")))
        arow=standings.get(comp,{}).get(str(away.get("id")))
        prediction=None; prob=None
        if hrow and arow:
            # Estimate expected goals from each team's attack and opponent's defense.
            rows=list(standings.get(comp,{}).values())
            total_played=sum(x.get("playedGames",0) for x in rows)
            league_home=sum(x.get("goalsFor",0) for x in rows)/max(total_played,1)
            league_away=sum(x.get("goalsAgainst",0) for x in rows)/max(total_played,1)
            h_attack=hrow.get("goalsFor",0)/max(hrow.get("playedGames",1),1)
            h_def=hrow.get("goalsAgainst",0)/max(hrow.get("playedGames",1),1)
            a_attack=arow.get("goalsFor",0)/max(arow.get("playedGames",1),1)
            a_def=arow.get("goalsAgainst",0)/max(arow.get("playedGames",1),1)
            # Shrink small samples toward league average.
            lam_h=max(.15,min(4.0,0.55*h_attack+0.25*a_def+0.20*max(league_home,0.8)))
            lam_a=max(.15,min(4.0,0.55*a_attack+0.25*h_def+0.20*max(league_away,0.6)))
            candidates=[]
            for hg in range(6):
                for ag in range(6):
                    candidates.append((poisson(lam_h,hg)*poisson(lam_a,ag),hg,ag))
            best=max(candidates)
            prob=round(best[0]*100,1)
            prediction=f"{best[1]}-{best[2]}"
        score=m.get("score",{}).get("fullTime",{})
        hs=score.get("home"); aws=score.get("away")
        out.append({
            "id":m.get("id"),"utcDate":m.get("utcDate"),"status":m.get("status"),
            "competition":m.get("competition",{}).get("name",comp),
            "homeTeam":hname,"awayTeam":aname,"prediction":prediction,"probability":prob,
            "homeScore":hs,"awayScore":aws
        })
    out.sort(key=lambda x:x.get("utcDate") or "")
    os.makedirs("data",exist_ok=True)
    with open("data/matches.json","w",encoding="utf-8") as f:
        json.dump({"updatedAt":datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                   "dateFrom":date_from,"dateTo":date_to,"matches":out,
                   "note":"Pronostics statistiques indicatifs. Accès compétitions selon abonnement API."},f,ensure_ascii=False,indent=2)
    print(f"Wrote {len(out)} matches; standings loaded for {len(standings)} competitions.")
    if errors: print("Standings skipped: "+" | ".join(errors))

if __name__=="__main__":
    main()
