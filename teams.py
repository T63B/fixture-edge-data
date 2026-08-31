"""Resolve the team names research returns onto the names used in the ratings file."""

import difflib
import re

# Names where the everyday form and the data-file form differ enough that fuzzy
# matching is not safe to rely on.
ALIASES = {
    "nottingham forest": "Nott'm Forest",
    "notts forest": "Nott'm Forest",
    "manchester united": "Man United",
    "manchester city": "Man City",
    "man utd": "Man United",
    "mk dons": "Milton Keynes Dons",
    "milton keynes": "Milton Keynes Dons",
    "sheffield wednesday": "Sheffield Weds",
    "sheffield weds": "Sheffield Weds",
    "sheffield united": "Sheffield United",
    "sheff utd": "Sheffield United",
    "sheff wed": "Sheffield Weds",
    "wolverhampton wanderers": "Wolves",
    "wolverhampton": "Wolves",
    "tottenham hotspur": "Tottenham",
    "spurs": "Tottenham",
    "west bromwich albion": "West Brom",
    "west bromwich": "West Brom",
    "west ham united": "West Ham",
    "newcastle united": "Newcastle",
    "leeds united": "Leeds",
    "leicester city": "Leicester",
    "hull city": "Hull",
    "coventry city": "Coventry",
    "cardiff city": "Cardiff",
    "swansea city": "Swansea",
    "norwich city": "Norwich",
    "ipswich town": "Ipswich",
    "luton town": "Luton",
    "burnley fc": "Burnley",
    "brighton & hove albion": "Brighton",
    "brighton and hove albion": "Brighton",
    "afc bournemouth": "Bournemouth",
    "bristol rovers": "Bristol Rvs",
    "queens park rangers": "QPR",
    "qpr": "QPR",
    "preston north end": "Preston",
    "derby county": "Derby",
    "stoke city": "Stoke",
    "birmingham city": "Birmingham",
    "blackburn rovers": "Blackburn",
    "bolton wanderers": "Bolton",
    "wycombe wanderers": "Wycombe",
    "tranmere rovers": "Tranmere",
    "doncaster rovers": "Doncaster",
    "accrington stanley": "Accrington",
    "crewe alexandra": "Crewe",
    "port vale": "Port Vale",
    "plymouth argyle": "Plymouth",
    "peterborough united": "Peterboro",
    "peterborough": "Peterboro",
    "stockport county": "Stockport",
    "notts county": "Notts County",
    "newport county": "Newport County",
    "colchester united": "Colchester",
    "cambridge united": "Cambridge",
    "oxford united": "Oxford",
    "exeter city": "Exeter",
    "grimsby town": "Grimsby",
    "cheltenham town": "Cheltenham",
    "mansfield town": "Mansfield",
    "shrewsbury town": "Shrewsbury",
    "northampton town": "Northampton",
    "swindon town": "Swindon",
    "salford city": "Salford",
    "rotherham united": "Rotherham",
    "oldham athletic": "Oldham",
    "wigan athletic": "Wigan",
    "walsall fc": "Walsall",
    "barnet fc": "Barnet",
    "york city": "York",
    "chesterfield fc": "Chesterfield",
    "huddersfield town": "Huddersfield",
    "barnsley fc": "Barnsley",
    "burton albion": "Burton",
    "lincoln city": "Lincoln",
    "charlton athletic": "Charlton",
    "millwall fc": "Millwall",
    "watford fc": "Watford",
    "southampton fc": "Southampton",
    "middlesbrough fc": "Middlesbrough",
    "portsmouth fc": "Portsmouth",
    "wrexham afc": "Wrexham",
    "bradford city": "Bradford",
    "blackpool fc": "Blackpool",
    "gillingham fc": "Gillingham",
    "rochdale afc": "Rochdale",
    "fleetwood": "Fleetwood Town",
    "crawley": "Crawley Town",
    "leyton orient": "Leyton Orient",
    "afc wimbledon": "AFC Wimbledon",
    "wimbledon": "AFC Wimbledon",
}

_SUFFIXES = (" fc", " afc", " football club")


def _norm(s):
    s = s.lower().strip()
    s = s.replace("&", "and").replace(".", "").replace("'", "'")
    for suf in _SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
    return re.sub(r"\s+", " ", s).strip()


def resolve(name, known):
    """
    Map `name` onto one of `known` (the ratings file's team names).
    Returns (resolved_name, confidence) where confidence is 'exact', 'alias',
    'fuzzy' or None when no safe match exists.
    """
    if not name:
        return None, None
    if name in known:
        return name, "exact"

    n = _norm(name)
    by_norm = {_norm(k): k for k in known}
    if n in by_norm:
        return by_norm[n], "exact"
    if n in ALIASES and ALIASES[n] in known:
        return ALIASES[n], "alias"

    # Try dropping a trailing generic word ("Town", "City", "United", "Rovers")
    trimmed = re.sub(r"\s+(town|city|united|rovers|wanderers|athletic|county)$", "", n)
    if trimmed in by_norm:
        return by_norm[trimmed], "alias"

    match = difflib.get_close_matches(n, list(by_norm.keys()), n=1, cutoff=0.86)
    if match:
        return by_norm[match[0]], "fuzzy"
    return None, None


def resolve_all(names, known):
    """Resolve a list, returning (mapping, unresolved list)."""
    mapping, missing = {}, []
    for nm in names:
        r, how = resolve(nm, known)
        if r:
            mapping[nm] = r
        else:
            missing.append(nm)
    return mapping, missing
