"""
Fact templates in four languages. The engine renders every fact from a key
and parameters, so the same numbers come out in English, Spanish, German and
French with no model involved. This is the floor: the Personalizer agent on
Microsoft Foundry writes free prose in any language on top of these facts.

Numbers keep a decimal point in every language so the Verifier's number
check is language-agnostic.
"""
from __future__ import annotations

LANGS = ["en", "es", "de", "fr"]
NAMES = {"en": "English", "es": "Español", "de": "Deutsch", "fr": "Français"}

WORDS = {
    "en": {"saved": "saved", "off_target": "off target", "blocked": "blocked", "goal": "goal",
           "interception": "interception", "tackle": "tackle", "block": "block",
           "control": "control", "chaos": "chaos", "balanced": "balanced"},
    "es": {"saved": "parado", "off_target": "fuera", "blocked": "bloqueado", "goal": "gol",
           "interception": "intercepción", "tackle": "entrada", "block": "bloqueo",
           "control": "control", "chaos": "caos", "balanced": "equilibrado"},
    "de": {"saved": "gehalten", "off_target": "vorbei", "blocked": "geblockt", "goal": "Tor",
           "interception": "Ballgewinn", "tackle": "Tackling", "block": "Block",
           "control": "Kontrolle", "chaos": "Chaos", "balanced": "ausgeglichen"},
    "fr": {"saved": "arrêté", "off_target": "non cadré", "blocked": "contré", "goal": "but",
           "interception": "interception", "tackle": "tacle", "block": "contre",
           "control": "contrôle", "chaos": "chaos", "balanced": "équilibré"},
}

T = {
    "score": {
        "en": "Score at {clock}: {home} {hg}, {away} {ag}",
        "es": "Marcador en el {clock}: {home} {hg}, {away} {ag}",
        "de": "Spielstand bei {clock}: {home} {hg}, {away} {ag}",
        "fr": "Score à {clock} : {home} {hg}, {away} {ag}"},
    "team_shots": {
        "en": "{club}: {shots} shots, {xg} xG",
        "es": "{club}: {shots} tiros, {xg} xG",
        "de": "{club}: {shots} Schüsse, {xg} xG",
        "fr": "{club} : {shots} tirs, {xg} xG"},
    "team_poss": {
        "en": "{club}: {poss}% possession, {passes} passes at {acc}% accuracy",
        "es": "{club}: {poss}% de posesión, {passes} pases con un {acc}% de acierto",
        "de": "{club}: {poss}% Ballbesitz, {passes} Pässe mit {acc}% Genauigkeit",
        "fr": "{club} : {poss}% de possession, {passes} passes réussies à {acc}%"},
    "interceptions": {
        "en": "{name} made {n} interceptions",
        "es": "{name} hizo {n} intercepciones",
        "de": "{name} hatte {n} Ballgewinne durch Abfangen",
        "fr": "{name} a réalisé {n} interceptions"},
    "threat_prevented": {
        "en": "{name} prevented {tp} threat (sum of danger stopped) and about {xgp} xG",
        "es": "{name} evitó {tp} de amenaza (suma del peligro frenado) y unos {xgp} xG",
        "de": "{name} verhinderte {tp} Bedrohung (Summe der gestoppten Gefahr) und etwa {xgp} xG",
        "fr": "{name} a empêché {tp} de menace (somme du danger stoppé) et environ {xgp} xG"},
    "attacks_ended": {
        "en": "{name} ended {n} opposition attacks",
        "es": "{name} cortó {n} ataques rivales",
        "de": "{name} beendete {n} gegnerische Angriffe",
        "fr": "{name} a stoppé {n} attaques adverses"},
    "goals": {
        "en": "{name} scored {n}",
        "es": "{name} marcó {n}",
        "de": "{name} erzielte {n} Tor(e)",
        "fr": "{name} a marqué {n}"},
    "shots": {
        "en": "{name}: {shots} shots worth {xg} xG",
        "es": "{name}: {shots} tiros por valor de {xg} xG",
        "de": "{name}: {shots} Schüsse im Wert von {xg} xG",
        "fr": "{name} : {shots} tirs pour {xg} xG"},
    "creation": {
        "en": "{name} created {dc} danger with his passing ({pp} progressive passes)",
        "es": "{name} generó {dc} de peligro con sus pases ({pp} pases progresivos)",
        "de": "{name} erzeugte {dc} Gefahr mit seinen Pässen ({pp} progressive Pässe)",
        "fr": "{name} a créé {dc} de danger par ses passes ({pp} passes progressives)"},
    "pass_quality": {
        "en": "{name} completed {acc}% of {passes} passes at an average difficulty of {diff} out of 100",
        "es": "{name} completó el {acc}% de {passes} pases con una dificultad media de {diff} sobre 100",
        "de": "{name} brachte {acc}% von {passes} Pässen an, bei einer mittleren Schwierigkeit von {diff} von 100",
        "fr": "{name} a réussi {acc}% de {passes} passes pour une difficulté moyenne de {diff} sur 100"},
    "physical": {
        "en": "{name} covered {km} km with {sprints} sprints",
        "es": "{name} recorrió {km} km con {sprints} sprints",
        "de": "{name} lief {km} km mit {sprints} Sprints",
        "fr": "{name} a parcouru {km} km avec {sprints} sprints"},
    "positioning": {
        "en": "{name} was screening the line between ball and his own goal for {pct}% of defending time",
        "es": "{name} tapó la línea entre el balón y su portería el {pct}% del tiempo defensivo",
        "de": "{name} schirmte die Linie zwischen Ball und eigenem Tor {pct}% der Verteidigungszeit ab",
        "fr": "{name} a couvert la ligne entre le ballon et son but pendant {pct}% du temps défensif"},
    # distances: the data is in metres; the English fact states yards too, so the
    # Verifier accepts either and a pundit can say "from 25 yards"
    "m_goal": {
        "en": "GOAL {clock}: {name} ({club}) scored from {yd} yards ({dist} m), xG {xg}",
        "es": "GOL {clock}: {name} ({club}) marcó desde {dist} m, xG {xg}",
        "de": "TOR {clock}: {name} ({club}) traf aus {dist} m, xG {xg}",
        "fr": "BUT {clock} : {name} ({club}) a marqué de {dist} m, xG {xg}"},
    "m_chance": {
        "en": "Chance {clock}: {name} shot from {yd} yards ({dist} m), xG {xg}, {outcome}",
        "es": "Ocasión {clock}: {name} tiró desde {dist} m, xG {xg}, {outcome}",
        "de": "Chance {clock}: {name} schoss aus {dist} m, xG {xg}, {outcome}",
        "fr": "Occasion {clock} : {name} a tiré de {dist} m, xG {xg}, {outcome}"},
    "m_key_pass": {
        "en": "Key pass {clock}: {name} found {receiver} with a {yd}-yard pass ({dist} m), danger {d0} to {d1}, difficulty {diff}",
        "es": "Pase clave {clock}: {name} encontró a {receiver} con un pase de {dist} m, peligro de {d0} a {d1}, dificultad {diff}",
        "de": "Schlüsselpass {clock}: {name} fand {receiver} mit einem {dist} m Pass, Gefahr {d0} auf {d1}, Schwierigkeit {diff}",
        "fr": "Passe clé {clock} : {name} a trouvé {receiver} d'une passe de {dist} m, danger de {d0} à {d1}, difficulté {diff}"},
    "m_speed": {
        "en": "{clock}: {name} hit {kmh} km/h ({v} m/s), the fastest sprint of the match so far",
        "es": "{clock}: {name} alcanzó {kmh} km/h ({v} m/s), el sprint más rápido del partido hasta ahora",
        "de": "{clock}: {name} erreichte {kmh} km/h ({v} m/s), der bisher schnellste Sprint des Spiels",
        "fr": "{clock} : {name} a atteint {kmh} km/h ({v} m/s), le sprint le plus rapide du match jusqu'ici"},
    "m_km": {
        "en": "{clock}: {name} passed {v} km covered",
        "es": "{clock}: {name} superó los {v} km recorridos",
        "de": "{clock}: {name} überschritt {v} km Laufstrecke",
        "fr": "{clock} : {name} a dépassé {v} km parcourus"},
    "m_stop": {
        "en": "Stop {clock}: {name} {action} with danger {d} stopped, about {xgp} xG prevented",
        "es": "Corte {clock}: {name}, {action} con {d} de peligro frenado, unos {xgp} xG evitados",
        "de": "Stopp {clock}: {name}, {action} bei Gefahr {d} gestoppt, etwa {xgp} xG verhindert",
        "fr": "Arrêt {clock} : {name}, {action} avec {d} de danger stoppé, environ {xgp} xG évités"},
    "m_momentum": {
        "en": "Momentum shift in {window}: {club} took over, home danger share {prev} to {now}",
        "es": "Cambio de inercia en {window}: {club} tomó el mando, cuota de peligro local de {prev} a {now}",
        "de": "Momentumwechsel in {window}: {club} übernahm, Heim-Gefahrenanteil von {prev} auf {now}",
        "fr": "Bascule du momentum en {window} : {club} a pris le dessus, part de danger domicile de {prev} à {now}"},
    "m_chaos": {
        "en": "Chaos spell {window}: {n} possession changes, {rate} per minute",
        "es": "Fase de caos {window}: {n} cambios de posesión, {rate} por minuto",
        "de": "Chaosphase {window}: {n} Ballbesitzwechsel, {rate} pro Minute",
        "fr": "Phase de chaos {window} : {n} changements de possession, {rate} par minute"},
    "rhythm": {
        "en": "Match rhythm: {c} control windows, {k} chaos windows, {b} balanced (5-minute windows)",
        "es": "Ritmo del partido: {c} tramos de control, {k} de caos, {b} equilibrados (tramos de 5 minutos)",
        "de": "Spielrhythmus: {c} Kontrollphasen, {k} Chaosphasen, {b} ausgeglichen (5-Minuten-Fenster)",
        "fr": "Rythme du match : {c} fenêtres de contrôle, {k} de chaos, {b} équilibrées (fenêtres de 5 minutes)"},
    # overlay captions (short, broadcast register)
    "o_goal": {"en": "GOAL {name}. xG {xg}", "es": "GOL {name}. xG {xg}", "de": "TOR {name}. xG {xg}", "fr": "BUT {name}. xG {xg}"},
    "o_chance": {"en": "{name}, {xg} xG. {verdict}", "es": "{name}, {xg} xG. {verdict}", "de": "{name}, {xg} xG. {verdict}", "fr": "{name}, {xg} xG. {verdict}"},
    "o_key_pass": {"en": "{name} to {receiver}. {dist}, difficulty {diff}. Proper ball",
                   "es": "{name} para {receiver}. {dist}, dificultad {diff}. Balón de verdad",
                   "de": "{name} auf {receiver}. {dist}, Schwierigkeit {diff}. Richtiger Ball",
                   "fr": "{name} pour {receiver}. {dist}, difficulté {diff}. Un vrai ballon"},
    "o_speed": {"en": "{name}, {kmh} km/h. Quickest of the match", "es": "{name}, {kmh} km/h. El más rápido del partido",
                "de": "{name}, {kmh} km/h. Schnellster des Spiels", "fr": "{name}, {kmh} km/h. Le plus rapide du match"},
    "o_km": {"en": "{name} past {v} km. Engine", "es": "{name} pasa los {v} km. Motor", "de": "{name} über {v} km. Motor", "fr": "{name} passe les {v} km. Moteur"},
    "o_stop": {"en": "{name} {act}. Danger {d} gone", "es": "{name} {act}. {d} de peligro, fuera",
               "de": "{name} {act}. Gefahr {d} weg", "fr": "{name} {act}. Danger {d} envolé"},
    "o_momentum": {"en": "Momentum. {club} have it", "es": "Inercia. La tiene el {club}", "de": "Momentum. {club} hat es", "fr": "Momentum. {club} l'a"},
    "o_chaos": {"en": "Chaos. {n} turnovers in five minutes", "es": "Caos. {n} pérdidas en cinco minutos", "de": "Chaos. {n} Ballverluste in fünf Minuten", "fr": "Chaos. {n} pertes en cinq minutes"},
    # local narrator connectives
    "why": {"en": "Why it matters: the goals get the replays, but {name} was ending attacks before they started",
            "es": "Por qué importa: los goles se llevan las repeticiones, pero {name} cortaba los ataques antes de que empezaran",
            "de": "Warum es zählt: die Tore bekommen die Wiederholungen, aber {name} beendete Angriffe, bevor sie begannen",
            "fr": "Pourquoi ça compte : les buts ont les ralentis, mais {name} stoppait les attaques avant qu'elles ne commencent"},
    "thinks": {"en": "How {name} thinks: after winning the ball his first action is usually to go {dir}",
               "es": "Cómo piensa {name}: tras recuperar el balón su primera acción suele ser {dir}",
               "de": "So denkt {name}: nach dem Ballgewinn ist seine erste Aktion meist {dir}",
               "fr": "Comment pense {name} : après avoir récupéré le ballon, sa première action est le plus souvent {dir}"},
    "dir": {"en": {"forward": "forward", "sideways": "sideways", "backward": "backward", "carry": "carry", "shot": "shoot"},
            "es": {"forward": "hacia delante", "sideways": "en horizontal", "backward": "hacia atrás", "carry": "conducir", "shot": "tirar"},
            "de": {"forward": "nach vorn", "sideways": "zur Seite", "backward": "nach hinten", "carry": "dribbeln", "shot": "schießen"},
            "fr": {"forward": "vers l'avant", "sideways": "latérale", "backward": "vers l'arrière", "carry": "la conduite", "shot": "tirer"}},
    "best": {"en": "Best attribute: {m}", "es": "Mejor cualidad: {m}", "de": "Stärkste Eigenschaft: {m}", "fr": "Meilleur atout : {m}"},
    "work": {"en": "One thing to work on: {m}", "es": "Algo que mejorar: {m}", "de": "Daran arbeiten: {m}", "fr": "Un point à travailler : {m}"},
    "drill": {"en": "Drill to try: shadow the line between the ball and your own goal for five minutes of a small-sided game",
              "es": "Ejercicio: sigue la línea entre el balón y tu portería durante cinco minutos de un partidillo",
              "de": "Übung: fünf Minuten im Kleinfeldspiel nur die Linie zwischen Ball und eigenem Tor abschirmen",
              "fr": "Exercice : suis la ligne entre le ballon et ton but pendant cinq minutes d'un jeu réduit"},
}


METRIC = {
    "interceptions": {"en": "passes cut out", "es": "pases interceptados", "de": "abgefangene Pässe", "fr": "passes interceptées"},
    "pressures": {"en": "closing down the ball carrier", "es": "presionar al portador", "de": "Anlaufen des Ballführers", "fr": "pression sur le porteur"},
    "tackles_won": {"en": "tackles won", "es": "entradas ganadas", "de": "gewonnene Tacklings", "fr": "tacles gagnés"},
    "tackle_success": {"en": "tackles that win the ball", "es": "entradas que ganan el balón", "de": "Tacklings mit Ballgewinn", "fr": "tacles qui récupèrent le ballon"},
    "passes": {"en": "passes made", "es": "pases dados", "de": "gespielte Pässe", "fr": "passes données"},
    "pass_accuracy": {"en": "passes that find a teammate", "es": "pases que llegan", "de": "angekommene Pässe", "fr": "passes qui arrivent"},
    "pass_difficulty": {"en": "difficulty of passes attempted", "es": "dificultad de los pases", "de": "Schwierigkeit der Pässe", "fr": "difficulté des passes"},
    "progressive_passes": {"en": "forward passes", "es": "pases hacia delante", "de": "Pässe nach vorn", "fr": "passes vers l'avant"},
    "passes_into_danger": {"en": "passes into dangerous areas", "es": "pases a zonas de peligro", "de": "Pässe in gefährliche Zonen", "fr": "passes dans les zones dangereuses"},
    "danger_created": {"en": "danger created by passing", "es": "peligro creado con el pase", "de": "durch Pässe erzeugte Gefahr", "fr": "danger créé par les passes"},
    "carries": {"en": "runs with the ball", "es": "conducciones", "de": "Dribblings", "fr": "conduites de balle"},
    "progressive_carries": {"en": "runs forward with the ball", "es": "conducciones hacia delante", "de": "Dribblings nach vorn", "fr": "conduites vers l'avant"},
    "carry_m": {"en": "ground covered on the ball", "es": "metros conducidos", "de": "Meter am Ball", "fr": "mètres balle au pied"},
    "shots": {"en": "shots", "es": "tiros", "de": "Schüsse", "fr": "tirs"},
    "xg": {"en": "quality of chances", "es": "calidad de las ocasiones", "de": "Qualität der Chancen", "fr": "qualité des occasions"},
    "goals": {"en": "goals", "es": "goles", "de": "Tore", "fr": "buts"},
    "blocks": {"en": "shots blocked", "es": "tiros bloqueados", "de": "geblockte Schüsse", "fr": "tirs contrés"},
    "ball_recoveries": {"en": "balls won back", "es": "balones recuperados", "de": "Ballrückgewinne", "fr": "ballons récupérés"},
    "threat_prevented": {"en": "attacks stopped early", "es": "ataques frenados a tiempo", "de": "früh gestoppte Angriffe", "fr": "attaques stoppées tôt"},
    "xg_prevented": {"en": "goals saved by stopping attacks", "es": "goles evitados al frenar ataques", "de": "durch Stopps verhinderte Tore", "fr": "buts évités en stoppant les attaques"},
    "screening": {"en": "time between the ball and his goal", "es": "tiempo entre el balón y su portería", "de": "Zeit zwischen Ball und eigenem Tor", "fr": "temps entre le ballon et son but"},
    "distance_km": {"en": "distance covered", "es": "distancia recorrida", "de": "Laufstrecke", "fr": "distance parcourue"},
    "sprints": {"en": "sprints", "es": "sprints", "de": "Sprints", "fr": "sprints"},
    "top_speed_ms": {"en": "top speed", "es": "velocidad máxima", "de": "Höchstgeschwindigkeit", "fr": "vitesse de pointe"},
    "time_to_release": {"en": "time on the ball before passing", "es": "tiempo con el balón antes de pasar", "de": "Zeit am Ball vor dem Pass", "fr": "temps balle au pied avant la passe"},
}


def metric(key: str, lang: str) -> str:
    k = key.replace("_p90", "")
    return METRIC.get(k, {}).get(lang) or METRIC.get(k, {}).get("en") or k.replace("_", " ")


def render(key: str, lang: str, **params) -> str:
    tpl = T[key].get(lang) or T[key]["en"]
    return tpl.format(**params)


def word(key: str, lang: str) -> str:
    return WORDS.get(lang, WORDS["en"]).get(key, key)


OVERLAY_ACT = {
    "en": {"interception": "reads it", "tackle": "wins it", "block": "blocks it"},
    "es": {"interception": "la lee", "tackle": "la gana", "block": "la bloquea"},
    "de": {"interception": "liest es", "tackle": "gewinnt ihn", "block": "blockt"},
    "fr": {"interception": "la lit", "tackle": "la gagne", "block": "la contre"},
}
VERDICT = {
    "en": ["Half chance", "Decent chance", "Should score"],
    "es": ["Media ocasión", "Buena ocasión", "Tiene que marcar"],
    "de": ["Halbe Chance", "Gute Chance", "Muss rein"],
    "fr": ["Demi-occasion", "Bonne occasion", "Doit marquer"],
}


def all_langs(key: str, **params) -> dict[str, str]:
    """Render a fact in every language. Params that are enumerations (outcome,
    action) are passed as raw keys and translated per language; a param whose
    value is a dict keyed by language is picked per language."""
    out = {}
    for lang in LANGS:
        p = {}
        for k, v in params.items():
            if isinstance(v, dict) and set(v) & set(LANGS):
                p[k] = v.get(lang) or v.get("en")
            else:
                p[k] = v
        for k in ("outcome", "action"):
            if k in p:
                p[k] = word(p[k], lang)
        out[lang] = render(key, lang, **p)
    return out
