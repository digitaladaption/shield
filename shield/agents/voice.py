"""
The pundit voice.

Every sentence here is built from a verified fact and ends with its citation,
so the Verifier treats it exactly like the model's output. The register is a
British co-commentator talking to the viewer: judgement first, the number as
proof, short sentences, football words. Nobody is being impersonated; this
is the register, not a person.

Rules the model gets too (STYLE_GUIDE) and the Verifier enforces (BANNED):
no exclamation marks, no em dashes, none of the words AI reaches for.
"""
from __future__ import annotations

import re

from shield.engine import units

STYLE_GUIDE = """VOICE. You are a former top-level player talking to the viewer from the studio. Direct, warm, a bit blunt.
- Judgement first, number second, as proof. "He's read it fourteen times today" beats "He made 14 interceptions".
- Talk to the viewer: "look at", "watch", "you see where he is".
- Short sentences. One idea each. Football words: reads it, steps in, shows for it, between the lines, in behind,
  gets his body in the way, second ball, on the half-turn, lets it run, that's his job.
- Surname only after the first mention. No club suffixes in brackets.
- Never gush. No exclamation marks. No em dashes. None of these words: showcase, testament, masterclass, pivotal,
  crucial, delve, remarkable, incredible, truly, elevate, seamless, robust, unleash, journey, tapestry, underscores,
  game-changer, world-class, it's worth noting, in the world of, overall.
- Good: "Nobody's clapping that, but that's the game. Okonkwo-Hale has ended seventeen attacks before they got near the box."
- Bad: "Okonkwo-Hale delivered a defensive masterclass, showcasing remarkable awareness!"
"""

BANNED = ["showcase", "showcasing", "testament", "masterclass", "pivotal", "crucial", "delve", "remarkable", "incredible",
          "truly", "elevate", "elevating", "seamless", "robust", "unleash", "journey", "tapestry", "underscore",
          "game-changer", "game changer", "world-class", "it's worth noting", "in the world of", "overall", "stunning",
          "phenomenal", "sensational", "mesmeri", "meticulous", "beacon", "symphony", "realm", "dazzl", "breathtaking"]
BANNED_CHARS = ["!", "—"]  # exclamation marks, em dashes

# words the style check leaves alone in other languages (they are normal there)
_SAFE_NON_EN = {"es": ["crucial", "incre"], "de": [], "fr": ["crucial", "incroyable", "remarquable"]}


def style_problems(sentence: str, lang: str = "en") -> list[str]:
    low = sentence.lower()
    out = []
    for ch in BANNED_CHARS:
        if ch in sentence:
            out.append("no exclamation marks or em dashes" if ch == "!" or ch == "—" else f"banned character {ch}")
            break
    safe = _SAFE_NON_EN.get(lang, [])
    for w in BANNED:
        if any(w.startswith(sf) for sf in safe):
            continue
        if w in low:
            out.append(f"avoid '{w}'")
    return out


def _pick(variants: list, seed: str) -> str:
    h = sum(ord(c) * (i + 1) for i, c in enumerate(seed))
    return variants[h % len(variants)]


def surname(full: str) -> str:
    return full.split()[-1] if full else full


def xg_word(xg: float, lang: str) -> str:
    W = {
        "en": ["not even a one-in-ten chance", "a half chance", "a proper chance", "one he should be scoring"],
        "es": ["ni una ocasión de una entre diez", "media ocasión", "una ocasión de verdad", "una que tiene que meter"],
        "de": ["nicht mal eine Eins-zu-zehn-Chance", "eine halbe Chance", "eine echte Chance", "eine, die er machen muss"],
        "fr": ["même pas une chance sur dix", "une demi-occasion", "une vraie occasion", "une qu'il doit mettre"],
    }[lang]
    return W[0] if xg < 0.1 else W[1] if xg < 0.2 else W[2] if xg < 0.35 else W[3]


def danger_word(d: float, lang: str) -> str:
    W = {
        "en": ["early", "building", "getting dangerous", "about to hurt them"],
        "es": ["todavía lejos", "creciendo", "ya peligroso", "a punto de hacer daño"],
        "de": ["noch früh", "im Aufbau", "schon gefährlich", "kurz vorm Zuschlagen"],
        "fr": ["encore tôt", "en construction", "qui devient dangereuse", "sur le point de faire mal"],
    }[lang]
    return W[0] if d < 0.2 else W[1] if d < 0.4 else W[2] if d < 0.6 else W[3]


# --------------------------------------------------------------------------- sentence patterns
# Each key: lang -> list of patterns. {s} is the surname, {name} the full name. Patterns end without a full stop;
# the citation is appended, then the full stop. Any number used must come from the fact's own params.
P = {
    "score": {
        "en": ["{hg}-{ag} to {leader} {when}, and the scoreline doesn't tell you half of it",
               "{hg}-{ag} {when}, and I want to show you why it's only {hg}-{ag}",
               "{hg}-{ag} to {leader} {when}, and the number that matters isn't on the scoreboard"],
        "es": ["{hg}-{ag} para el {leader} {when}, y el marcador no cuenta ni la mitad",
               "{hg}-{ag} {when}, y te voy a enseñar por qué es solo {hg}-{ag}"],
        "de": ["{hg}:{ag} für {leader} {when}, und der Spielstand erzählt nicht die Hälfte",
               "{hg}:{ag} {when}, und ich zeig dir, warum es nur {hg}:{ag} steht"],
        "fr": ["{hg}-{ag} pour {leader} {when}, et le score ne raconte pas la moitié de l'histoire",
               "{hg}-{ag} {when}, et je vais vous montrer pourquoi ce n'est que {hg}-{ag}"],
    },
    "score_draw": {
        "en": ["{hg}-{ag} {when}, and it's the quiet stuff that's kept it that way"],
        "es": ["{hg}-{ag} {when}, y lo que lo mantiene así es el trabajo silencioso"],
        "de": ["{hg}:{ag} {when}, und die stille Arbeit hält es so"],
        "fr": ["{hg}-{ag} {when}, et c'est le travail de l'ombre qui le maintient ainsi"],
    },
    "m_goal": {
        "en": ["The goal comes in {clock}, {name} {where}, {xgw} at {xg} xG, and he's put it away",
               "{clock}, and {name} scores {where}, {xg} xG, {xgw}, but they all count",
               "{name}'s goal in {clock} will be on every reel tonight, {where}, {xg} xG, and it's the easy bit to show"],
        "es": ["El gol llega en el {clock}, {name} {where}, {xgw} con {xg} xG, y la ha metido",
               "{clock}, y {name} marca {where}, {xg} xG, {xgw}, pero todos cuentan"],
        "de": ["Das Tor fällt in {clock}, {name} {where}, {xgw} bei {xg} xG, und er macht ihn rein",
               "In {clock}, {name} trifft {where}, {xg} xG, {xgw}, aber die zählen alle"],
        "fr": ["Le but arrive à {clock}, {name} {where}, {xgw} à {xg} xG, et il l'a mis",
               "{clock}, et {name} marque {where}, {xg} xG, {xgw}, mais ils comptent tous"],
    },
    "m_chance": {
        "en": ["{clock}, and {name} gets a shot away {where}, {xg} xG, {xgw}, and it's {outcome}",
               "Look at {clock}, {name} {where}, {xgw} at {xg} xG, {outcome}, and he knows it"],
        "es": ["{clock}, {name} tira {where}, {xg} xG, {xgw}, y acaba {outcome}",
               "Ojo al {clock}, {name} {where}, {xgw} con {xg} xG, {outcome}, y él lo sabe"],
        "de": ["In {clock}, {name} kommt {where} zum Abschluss, {xg} xG, {xgw}, und er wird {outcome}",
               "Schau auf {clock}, {name} {where}, {xgw} bei {xg} xG, {outcome}, und er weiß es"],
        "fr": ["{clock}, {name} frappe {where}, {xg} xG, {xgw}, et c'est {outcome}",
               "Regardez à {clock}, {name} {where}, {xgw} à {xg} xG, {outcome}, et il le sait"],
    },
    "m_key_pass": {
        "en": ["Watch the pass in {clock}, {name} finds {receiver} with a {yd}-yard ball, the danger goes from {d0} to {d1}, difficulty {diff}, and that's a proper pass",
               "{clock}, and it's {name} to {receiver}, {yd} yards, and it takes the danger from {d0} to {d1} in one go, difficulty {diff}, that's the pass that opens them"],
        "es": ["Ojo al pase del {clock}, {name} encuentra a {receiver} a {dist} metros, el peligro pasa de {d0} a {d1}, dificultad {diff}, y eso es un balón de verdad",
               "{clock}, {name} para {receiver}, {dist} metros, y el peligro sube de {d0} a {d1} de golpe, dificultad {diff}, ese es el pase que los abre"],
        "de": ["Schau dir den Pass in {clock} an, {name} findet {receiver} über {dist} Meter, die Gefahr geht von {d0} auf {d1}, Schwierigkeit {diff}, das ist ein richtiger Ball",
               "In {clock}, {name} auf {receiver}, {dist} Meter, und die Gefahr springt von {d0} auf {d1}, Schwierigkeit {diff}, das ist der Pass, der sie aufmacht"],
        "fr": ["Regardez la passe à {clock}, {name} trouve {receiver} à {dist} mètres, le danger passe de {d0} à {d1}, difficulté {diff}, et ça c'est un vrai ballon",
               "{clock}, {name} pour {receiver}, {dist} mètres, et le danger monte de {d0} à {d1} d'un coup, difficulté {diff}, c'est la passe qui les ouvre"],
    },
    "m_stop": {
        "en": ["{clock}, and {name} {act} with the attack {dw} at {d}, call it {xgp} xG taken off the board, and nobody's clapping it",
               "Now watch {clock}, the attack's {dw} at {d} and {name} {act}, {xgp} xG that never arrives, and that's the game right there",
               "{name} in {clock}, {act} with the danger at {d}, about {xgp} xG gone, and you won't see it on the highlights"],
        "es": ["{clock}, {name} {act} con el ataque {dw} a {d}, pongamos {xgp} xG que desaparecen, y nadie lo aplaude",
               "Ahora mira el {clock}, el ataque está {dw} a {d} y {name} {act}, {xgp} xG que nunca llegan, y eso es el partido"],
        "de": ["In {clock}, {name} {act}, der Angriff {dw} bei {d}, sagen wir {xgp} xG vom Tisch, und keiner klatscht dafür",
               "Jetzt schau auf {clock}, der Angriff ist {dw} bei {d} und {name} {act}, {xgp} xG, die nie ankommen, und genau das ist das Spiel"],
        "fr": ["{clock}, {name} {act} avec l'attaque {dw} à {d}, disons {xgp} xG rayés de la carte, et personne n'applaudit",
               "Maintenant regardez à {clock}, l'attaque est {dw} à {d} et {name} {act}, {xgp} xG qui n'arrivent jamais, et c'est ça le match"],
    },
    "interceptions": {
        "en": ["{name}'s cut out {n} passes today, and that's not luck, that's seeing it a second before everyone else",
               "{n} passes read and cut out by {name}, and reading it is the hard bit, anyone can run",
               "Count them, {n} interceptions from {name}, and every one of them is a decision made before the ball's even played"],
        "es": ["{name} ha cortado {n} pases hoy, y eso no es suerte, es verlo un segundo antes que los demás",
               "{n} pases leídos y cortados por {name}, y leerlo es lo difícil, correr corre cualquiera"],
        "de": ["{name} hat heute {n} Pässe abgefangen, und das ist kein Glück, das ist eine Sekunde früher sehen als alle anderen",
               "{n} Pässe gelesen und abgefangen von {name}, und das Lesen ist der schwere Teil, laufen kann jeder"],
        "fr": ["{name} a coupé {n} passes aujourd'hui, et ce n'est pas de la chance, c'est voir une seconde avant tout le monde",
               "{n} passes lues et coupées par {name}, et lire le jeu c'est le plus dur, courir tout le monde sait faire"],
    },
    "threat_prevented": {
        "en": ["Add it up and {name} has taken {tp} of danger out of the game, call it {xgp} xG that never arrived",
               "{name}, {tp} of danger stopped and about {xgp} xG that never happened, and that's a number nobody puts on a graphic"],
        "es": ["Súmalo y {name} ha quitado {tp} de peligro del partido, pongamos {xgp} xG que nunca llegaron",
               "{name}, {tp} de peligro frenado y unos {xgp} xG que nunca existieron, y ese número nadie lo pone en un gráfico"],
        "de": ["Rechne es zusammen, {name} hat {tp} an Gefahr aus dem Spiel genommen, sagen wir {xgp} xG, die nie angekommen sind",
               "{name}, {tp} an Gefahr gestoppt und etwa {xgp} xG, die es nie gab, und diese Zahl packt keiner in eine Grafik"],
        "fr": ["Additionnez, {name} a retiré {tp} de danger du match, disons {xgp} xG qui ne sont jamais arrivés",
               "{name}, {tp} de danger stoppé et environ {xgp} xG qui n'ont jamais existé, et ce chiffre, personne ne le met à l'écran"],
    },
    "attacks_ended": {
        "en": ["{name} ended {n} attacks before they got anywhere near the box, and that's the job, that's exactly the job",
               "{n} attacks killed by {name} before they became anything, and the back four can thank him later",
               "Nobody's clapping that, but {name} has stopped {n} attacks at source today"],
        "es": ["{name} cortó {n} ataques antes de que se acercaran al área, y ese es el trabajo, exactamente ese",
               "{n} ataques muertos por {name} antes de ser nada, y la defensa ya le dará las gracias"],
        "de": ["{name} hat {n} Angriffe beendet, bevor sie auch nur in die Nähe des Strafraums kamen, und das ist der Job, genau das",
               "{n} Angriffe von {name} erstickt, bevor sie etwas wurden, und die Viererkette kann sich später bedanken"],
        "fr": ["{name} a stoppé {n} attaques avant qu'elles n'approchent la surface, et c'est ça le boulot, exactement ça",
               "{n} attaques tuées par {name} avant de devenir quelque chose, et la défense le remerciera plus tard"],
    },
    "goals": {
        "en": ["{name} with {n}, and that's what they pay him for"],
        "es": ["{name} con {n}, y para eso le pagan"],
        "de": ["{name} mit {n}, und dafür wird er bezahlt"],
        "fr": ["{name} avec {n}, et c'est pour ça qu'on le paie"],
    },
    "shots": {
        "en": ["{name} had {shots} shots worth {xg} xG, so he's getting in the right places even when it's not dropping",
               "{shots} shots from {name}, {xg} xG, he's in the right spots, the finishing is the next bit"],
        "es": ["{name} tuvo {shots} tiros por valor de {xg} xG, así que está llegando a los sitios aunque no caiga",
               "{shots} tiros de {name}, {xg} xG, está donde tiene que estar, la definición es el siguiente paso"],
        "de": ["{name} hatte {shots} Schüsse im Wert von {xg} xG, er kommt also in die richtigen Räume, auch wenn es nicht fällt",
               "{shots} Schüsse von {name}, {xg} xG, er steht richtig, der Abschluss ist der nächste Schritt"],
        "fr": ["{name} a eu {shots} tirs pour {xg} xG, donc il arrive aux bons endroits même quand ça ne rentre pas",
               "{shots} tirs de {name}, {xg} xG, il est aux bons endroits, la finition c'est l'étape suivante"],
    },
    "creation": {
        "en": ["{name} made {dc} of danger with his passing, {pp} forward balls, he's the one making them turn",
               "Every time {name} gets it he's looking forward, {pp} progressive passes, {dc} of danger created, that's a playmaker"],
        "es": ["{name} generó {dc} de peligro con el pase, {pp} balones hacia delante, él es quien los hace girar",
               "Cada vez que {name} la recibe mira hacia delante, {pp} pases progresivos, {dc} de peligro creado, eso es un organizador"],
        "de": ["{name} hat mit seinen Pässen {dc} an Gefahr erzeugt, {pp} Bälle nach vorn, er ist der, der sie zum Drehen bringt",
               "Jedes Mal, wenn {name} den Ball hat, schaut er nach vorn, {pp} progressive Pässe, {dc} an Gefahr, das ist ein Spielmacher"],
        "fr": ["{name} a créé {dc} de danger par ses passes, {pp} ballons vers l'avant, c'est lui qui les fait reculer",
               "À chaque fois que {name} la touche il regarde devant, {pp} passes progressives, {dc} de danger créé, ça c'est un meneur"],
    },
    "pass_quality": {
        "en": ["{name} completed {acc}% of {passes} passes at an average difficulty of {diff}, so don't tell me he's playing it safe",
               "{acc}% from {passes} passes, difficulty {diff} on average, {name} is taking the hard option and landing it"],
        "es": ["{name} completó el {acc}% de {passes} pases con una dificultad media de {diff}, así que no me digas que juega a lo fácil",
               "{acc}% de {passes} pases, dificultad {diff} de media, {name} elige la opción difícil y la acierta"],
        "de": ["{name} hat {acc}% von {passes} Pässen bei einer mittleren Schwierigkeit von {diff} angebracht, also erzähl mir nicht, er spielt auf Sicherheit",
               "{acc}% aus {passes} Pässen, Schwierigkeit {diff} im Schnitt, {name} wählt die schwere Option und bringt sie an"],
        "fr": ["{name} a réussi {acc}% de {passes} passes à une difficulté moyenne de {diff}, alors ne me dites pas qu'il joue la sécurité",
               "{acc}% sur {passes} passes, difficulté {diff} en moyenne, {name} prend l'option difficile et la réussit"],
    },
    "physical": {
        "en": ["{name}, {km} kilometres and {sprints} sprints, he's run himself into the ground for them",
               "{km} kilometres from {name} and {sprints} sprints, and he'll feel every one of them tomorrow"],
        "es": ["{name}, {km} kilómetros y {sprints} sprints, se ha dejado la vida por ellos",
               "{km} kilómetros de {name} y {sprints} sprints, y mañana los va a notar todos"],
        "de": ["{name}, {km} Kilometer und {sprints} Sprints, der hat sich für sie zerrissen",
               "{km} Kilometer von {name} und {sprints} Sprints, und morgen spürt er jeden einzelnen"],
        "fr": ["{name}, {km} kilomètres et {sprints} sprints, il s'est mis en pièces pour eux",
               "{km} kilomètres pour {name} et {sprints} sprints, et il va tous les sentir demain"],
    },
    "positioning": {
        "en": ["Look where {name} is when they've got it, between the ball and his own goal {pct}% of the time, and that's a decision, not luck",
               "{pct}% of the time they had the ball, {name} was on the line between it and his own goal, and that's a lad who understands the game"],
        "es": ["Mira dónde está {name} cuando ellos la tienen, entre el balón y su portería el {pct}% del tiempo, y eso es una decisión, no suerte",
               "El {pct}% del tiempo que tuvieron el balón, {name} estaba en la línea entre el balón y su portería, y eso es un chaval que entiende el juego"],
        "de": ["Schau, wo {name} steht, wenn sie den Ball haben, {pct}% der Zeit zwischen Ball und eigenem Tor, und das ist eine Entscheidung, kein Glück",
               "{pct}% der Zeit, in der sie den Ball hatten, stand {name} auf der Linie zwischen Ball und eigenem Tor, und das ist einer, der das Spiel versteht"],
        "fr": ["Regardez où est {name} quand ils ont le ballon, entre le ballon et son but {pct}% du temps, et ça c'est une décision, pas de la chance",
               "{pct}% du temps où ils avaient le ballon, {name} était sur la ligne entre le ballon et son but, et ça c'est un garçon qui comprend le jeu"],
    },
    "m_momentum": {
        "en": ["Then it turns in the {window} spell, {club} take hold of it, home danger share from {prev} to {now}, and you could feel it from the stands"],
        "es": ["Luego cambia en el tramo {window}, el {club} se hace con el partido, cuota de peligro local de {prev} a {now}, y se notaba desde la grada"],
        "de": ["Dann kippt es im Abschnitt {window}, {club} übernimmt, Heim-Gefahrenanteil von {prev} auf {now}, und das hat man von der Tribüne gespürt"],
        "fr": ["Puis ça bascule dans la période {window}, {club} prend le match en main, part de danger domicile de {prev} à {now}, et ça se sentait depuis les tribunes"],
    },
    "m_chaos": {
        "en": ["{window} is end to end, {n} turnovers, {rate} a minute, and that's when games get decided by who keeps their head"],
        "es": ["El tramo {window} es de ida y vuelta, {n} pérdidas, {rate} por minuto, y ahí los partidos los decide quien mantiene la cabeza fría"],
        "de": ["{window} geht hin und her, {n} Ballverluste, {rate} pro Minute, und da entscheidet sich ein Spiel daran, wer die Ruhe behält"],
        "fr": ["{window} c'est du jeu de transition pur, {n} pertes, {rate} par minute, et c'est là que les matchs se jouent sur le sang-froid"],
    },
    "rhythm": {
        "en": ["Across the ninety, {c} spells of control, {k} of chaos, {b} even, and the good sides win the chaos"],
        "es": ["En los noventa, {c} tramos de control, {k} de caos, {b} igualados, y los buenos equipos ganan el caos"],
        "de": ["Über die neunzig Minuten, {c} Phasen Kontrolle, {k} Chaos, {b} ausgeglichen, und gute Teams gewinnen das Chaos"],
        "fr": ["Sur les quatre-vingt-dix minutes, {c} périodes de contrôle, {k} de chaos, {b} équilibrées, et les bonnes équipes gagnent le chaos"],
    },
    "team_shots": {
        "en": ["{club} had {shots} shots for {xg} xG, {quality}"],
        "es": ["El {club} tuvo {shots} tiros para {xg} xG, {quality}"],
        "de": ["{club} hatte {shots} Schüsse für {xg} xG, {quality}"],
        "fr": ["{club} a eu {shots} tirs pour {xg} xG, {quality}"],
    },
    "team_poss": {
        "en": ["{club} had {poss}% of the ball, {passes} passes at {acc}%, so they could keep it, the question is what they did with it"],
        "es": ["El {club} tuvo el {poss}% del balón, {passes} pases al {acc}%, así que sabían conservarlo, la pregunta es qué hicieron con él"],
        "de": ["{club} hatte {poss}% Ballbesitz, {passes} Pässe bei {acc}%, sie konnten ihn also halten, die Frage ist, was sie damit gemacht haben"],
        "fr": ["{club} a eu {poss}% du ballon, {passes} passes à {acc}%, donc ils savaient le garder, la question c'est ce qu'ils en ont fait"],
    },
    "m_speed": {
        "en": ["{clock}, and {name} hits {kmh} kilometres an hour, quickest sprint of the match, and that's not a man coasting"],
        "es": ["{clock}, {name} se va a {kmh} kilómetros por hora, el sprint más rápido del partido"],
        "de": ["In {clock}, {name} geht auf {kmh} km/h, schnellster Sprint des Spiels"],
        "fr": ["{clock}, {name} monte à {kmh} km/h, le sprint le plus rapide du match"],
    },
    "m_km": {
        "en": ["{clock}, and {name} has just passed {v} kilometres, which tells you about the engine"],
        "es": ["{clock}, y {name} acaba de pasar los {v} kilómetros, lo que te dice del motor que tiene"],
        "de": ["In {clock}, und {name} hat gerade {v} Kilometer geknackt, das sagt dir alles über seinen Motor"],
        "fr": ["{clock}, et {name} vient de passer les {v} kilomètres, ça vous dit tout sur son moteur"],
    },
    # connective lines (cite the stop fact)
    "why": {
        "en": ["The goal gets the replay, {name} is why there was only one to find, and that's the bit I'd be showing the kids",
               "Everyone will talk about the finish, I'm talking about {name}, because he's the reason it stayed tight"],
        "es": ["El gol se lleva la repetición, {name} es el motivo de que solo hubiera uno que encontrar, y eso es lo que yo enseñaría a los chavales",
               "Todos hablarán del remate, yo hablo de {name}, porque él es la razón de que estuviera tan apretado"],
        "de": ["Das Tor bekommt die Wiederholung, {name} ist der Grund, warum es nur eines zu finden gab, und das würde ich den Kindern zeigen",
               "Alle reden über den Abschluss, ich rede über {name}, weil er der Grund ist, dass es eng blieb"],
        "fr": ["Le but aura le ralenti, {name} est la raison pour laquelle il n'y en avait qu'un à trouver, et c'est ça que je montrerais aux gamins",
               "Tout le monde parlera de la finition, moi je parle de {name}, parce que c'est lui la raison pour laquelle ça restait serré"],
    },
    "why_nogoal": {
        "en": ["Nobody's scored, and {name} is a big part of why, he's the one keeping it quiet at the back",
               "It's goalless and the clever money is on {name}, because every time it looked like opening up he shut it"],
        "es": ["Nadie ha marcado, y {name} tiene mucho que ver, es el que mantiene la calma atrás",
               "Sigue sin goles y el mérito es de {name}, porque cada vez que parecía abrirse él lo cerraba"],
        "de": ["Noch kein Tor, und {name} hat viel damit zu tun, er ist der, der es hinten ruhig hält",
               "Es steht torlos und das liegt an {name}, denn jedes Mal, wenn es aufzugehen drohte, hat er es zugemacht"],
        "fr": ["Personne n'a marqué, et {name} y est pour beaucoup, c'est lui qui garde le calme derrière",
               "Toujours 0 but et le mérite revient à {name}, parce qu'à chaque fois que ça s'ouvrait il a refermé"],
    },
    "why_many": {
        "en": ["Everyone will talk about the goals, I'm talking about {name}, because without him there'd have been a lot more",
               "The goals get the replays, {name} gets nothing, and he's the one who kept the count down"],
        "es": ["Todos hablarán de los goles, yo hablo de {name}, porque sin él habría habido muchos más",
               "Los goles se llevan las repeticiones, {name} no se lleva nada, y es el que mantuvo la cuenta baja"],
        "de": ["Alle reden über die Tore, ich rede über {name}, denn ohne ihn wären es deutlich mehr gewesen",
               "Die Tore bekommen die Wiederholungen, {name} bekommt nichts, und er hat die Zahl klein gehalten"],
        "fr": ["Tout le monde parlera des buts, moi je parle de {name}, parce que sans lui il y en aurait eu bien plus",
               "Les buts ont les ralentis, {name} n'a rien, et c'est lui qui a gardé le compte bas"],
    },
    # kid mode connectives
    "thinks": {
        "en": ["Here's how {s} thinks, the second he wins it his first idea is {dir}, more often than not, and that's a habit you can copy",
               "Watch what {s} does when he wins it, {dir}, straight away, and that's trained, not born"],
        "es": ["Así piensa {s}, en cuanto la recupera su primera idea suele ser {dir}, y eso es un hábito que puedes copiar"],
        "de": ["So denkt {s}, kaum hat er den Ball, ist seine erste Idee meistens {dir}, und das ist eine Gewohnheit, die du kopieren kannst"],
        "fr": ["Voilà comment pense {s}, dès qu'il récupère, sa première idée c'est le plus souvent {dir}, et ça c'est une habitude que tu peux copier"],
    },
    "best": {
        "en": ["His best bit is {m}, and that's where you start"],
        "es": ["Lo mejor que tiene es {m}, y por ahí se empieza"],
        "de": ["Seine stärkste Seite ist {m}, und da fängst du an"],
        "fr": ["Son point fort c'est {m}, et c'est par là que tu commences"],
    },
    "work": {
        "en": ["If I'm his coach I'm on him about {m}, because that's the one thing holding him back"],
        "es": ["Si yo fuera su entrenador le insistiría en {m}, porque es lo único que le frena"],
        "de": ["Wäre ich sein Trainer, ginge es jeden Tag um {m}, denn das ist das Einzige, was ihn bremst"],
        "fr": ["Si j'étais son coach je serais sur lui pour {m}, parce que c'est la seule chose qui le freine"],
    },
    "drill": {
        "en": ["Go and do it, five minutes of a small game where your only job is the line between the ball and your own goal"],
        "es": ["Ve y hazlo, cinco minutos de un partidillo donde tu único trabajo es la línea entre el balón y tu portería"],
        "de": ["Geh raus und mach es, fünf Minuten Kleinfeld, dein einziger Job ist die Linie zwischen Ball und eigenem Tor"],
        "fr": ["Vas-y et fais-le, cinq minutes de jeu réduit où ton seul boulot c'est la ligne entre le ballon et ton but"],
    },
}

ACT = {
    "en": {"interception": "reads it and steps in", "tackle": "gets across and wins it", "block": "gets his body in the way"},
    "es": {"interception": "la lee y se adelanta", "tackle": "llega y la gana", "block": "pone el cuerpo"},
    "de": {"interception": "liest es und geht dazwischen", "tackle": "kommt rüber und gewinnt ihn", "block": "wirft sich dazwischen"},
    "fr": {"interception": "la lit et intervient", "tackle": "arrive et la gagne", "block": "met son corps en opposition"},
}
OUTCOME = {
    "en": {"saved": "saved", "off_target": "off target", "blocked": "blocked", "goal": "in"},
    "es": {"saved": "parado", "off_target": "fuera", "blocked": "bloqueado", "goal": "dentro"},
    "de": {"saved": "gehalten", "off_target": "vorbei", "blocked": "geblockt", "goal": "drin"},
    "fr": {"saved": "arrêté", "off_target": "non cadré", "blocked": "contré", "goal": "dedans"},
}
QUALITY = {  # xg per shot
    "en": ["which tells you the quality wasn't there even when the volume was", "which is a threat, but not a relentless one", "and that's a side creating proper chances"],
    "es": ["lo que te dice que no hubo calidad aunque hubiera volumen", "que es amenaza, pero no constante", "y eso es un equipo creando ocasiones de verdad"],
    "de": ["was dir sagt, dass die Qualität fehlte, auch wenn die Menge da war", "das ist Gefahr, aber keine ständige", "und das ist ein Team, das echte Chancen kreiert"],
    "fr": ["ce qui vous dit que la qualité n'y était pas même quand le volume y était", "c'est une menace, mais pas une menace constante", "et ça c'est une équipe qui crée de vraies occasions"],
}
DIR = {
    "en": {"forward": "to play it forward", "sideways": "to keep it, sideways", "backward": "to keep it safe, back", "carry": "to carry it", "shot": "to shoot"},
    "es": {"forward": "jugarla hacia delante", "sideways": "conservarla, en horizontal", "backward": "asegurarla, hacia atrás", "carry": "conducirla", "shot": "tirar"},
    "de": {"forward": "nach vorn zu spielen", "sideways": "ihn zu halten, zur Seite", "backward": "ihn zu sichern, nach hinten", "carry": "zu dribbeln", "shot": "zu schießen"},
    "fr": {"forward": "jouer vers l'avant", "sideways": "la garder, latéralement", "backward": "la sécuriser, en retrait", "carry": "la porter", "shot": "tirer"},
}


def minute_phrase(clock: str, lang: str) -> str:
    """'39:40' -> 'the 40th minute' (football convention: the minute in progress)."""
    try:
        mm, ss = clock.split(":")
        m = int(mm) + (1 if int(ss) > 0 else 0)
    except ValueError:
        return clock
    m = max(1, m)
    if lang == "en":
        suf = "th" if 10 <= m % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(m % 10, "th")
        return f"the {m}{suf} minute"
    if lang == "es":
        return f"minuto {m}"      # the patterns supply the article: "en el minuto 40", "Ojo al minuto 40"
    if lang == "de":
        return f"Minute {m}"
    return f"la {m}e minute"


def when_phrase(clock: str, lang: str) -> str:
    """For the score line: 'at full time' or 'after 25 minutes'."""
    try:
        mm, ss = clock.split(":")
        m = int(mm) + (1 if int(ss) > 0 else 0)
    except ValueError:
        return clock
    if m >= 90:
        return {"en": "at full time", "es": "al final", "de": "nach Abpfiff", "fr": "au coup de sifflet final"}[lang]
    return {"en": f"after {m} minutes", "es": f"tras {m} minutos", "de": f"nach {m} Minuten", "fr": f"après {m} minutes"}[lang]


SKILL = {  # what a metric is, as a coach would say it to a kid
    "interceptions": {"en": "reading the pass", "es": "leer el pase", "de": "das Lesen der Pässe", "fr": "lire la passe"},
    "pressures": {"en": "closing people down", "es": "presionar", "de": "das Anlaufen", "fr": "le pressing"},
    "tackles_won": {"en": "winning the tackle", "es": "ganar la entrada", "de": "das Gewinnen der Zweikämpfe", "fr": "gagner le tacle"},
    "tackle_success": {"en": "picking the moment to tackle", "es": "elegir el momento de la entrada", "de": "das Timing im Tackling", "fr": "choisir le moment du tacle"},
    "passes": {"en": "keeping the ball moving", "es": "mover el balón", "de": "das Laufenlassen des Balls", "fr": "faire circuler le ballon"},
    "pass_accuracy": {"en": "finding a teammate", "es": "encontrar al compañero", "de": "das Finden des Mitspielers", "fr": "trouver le coéquipier"},
    "pass_difficulty": {"en": "trying the harder pass", "es": "intentar el pase difícil", "de": "der Mut zum schweren Pass", "fr": "tenter la passe difficile"},
    "progressive_passes": {"en": "playing forward", "es": "jugar hacia delante", "de": "das Spiel nach vorn", "fr": "jouer vers l'avant"},
    "passes_into_danger": {"en": "the final ball", "es": "el último pase", "de": "der letzte Pass", "fr": "la dernière passe"},
    "danger_created": {"en": "making things happen", "es": "generar peligro", "de": "das Erzeugen von Gefahr", "fr": "créer du danger"},
    "carries": {"en": "carrying the ball", "es": "conducir el balón", "de": "das Ballführen", "fr": "porter le ballon"},
    "progressive_carries": {"en": "driving forward with it", "es": "avanzar con el balón", "de": "das Vorwärtsdribbeln", "fr": "avancer balle au pied"},
    "carry_m": {"en": "carrying the ball", "es": "conducir el balón", "de": "das Ballführen", "fr": "porter le ballon"},
    "shots": {"en": "getting shots away", "es": "rematar", "de": "der Abschluss", "fr": "déclencher la frappe"},
    "xg": {"en": "finding the good chances", "es": "encontrar las buenas ocasiones", "de": "das Finden guter Chancen", "fr": "trouver les bonnes occasions"},
    "goals": {"en": "finishing", "es": "la definición", "de": "das Verwerten", "fr": "la finition"},
    "blocks": {"en": "blocking shots", "es": "bloquear tiros", "de": "das Blocken", "fr": "contrer les tirs"},
    "ball_recoveries": {"en": "winning it back", "es": "recuperar el balón", "de": "das Zurückholen des Balls", "fr": "récupérer le ballon"},
    "threat_prevented": {"en": "killing attacks early", "es": "matar los ataques pronto", "de": "das frühe Ersticken von Angriffen", "fr": "tuer les attaques tôt"},
    "xg_prevented": {"en": "killing attacks early", "es": "matar los ataques pronto", "de": "das frühe Ersticken von Angriffen", "fr": "tuer les attaques tôt"},
    "screening": {"en": "staying between the ball and the goal", "es": "quedarse entre el balón y la portería", "de": "das Bleiben zwischen Ball und Tor", "fr": "rester entre le ballon et le but"},
    "distance_km": {"en": "covering the ground", "es": "recorrer el campo", "de": "die Laufarbeit", "fr": "couvrir le terrain"},
    "sprints": {"en": "repeat sprints", "es": "los sprints repetidos", "de": "wiederholte Sprints", "fr": "les sprints répétés"},
    "top_speed_ms": {"en": "top speed", "es": "la velocidad punta", "de": "die Höchstgeschwindigkeit", "fr": "la vitesse de pointe"},
    "time_to_release": {"en": "getting the ball moving quicker", "es": "soltar el balón antes", "de": "das schnellere Abspielen", "fr": "relancer plus vite"},
}


def skill(metric: str, lang: str) -> str:
    k = metric.replace("_p90", "")
    d = SKILL.get(k)
    return (d.get(lang) or d["en"]) if d else k.replace("_", " ")


def surnames_after_first(text: str, roster: list[str]) -> str:
    """A pundit says the full name once, then the surname."""
    for full in roster:
        if text.count(full) > 1:
            first = text.index(full) + len(full)
            text = text[:first] + text[first:].replace(full, surname(full))
    return text


def render(fact: dict, lang: str, mode: str = "casual") -> str | None:
    """One pundit sentence for one fact, with its citation. None if the key has no pattern."""
    key = fact.get("key") or ""
    p = dict(fact.get("params") or {})
    if "name" in p:
        p["s"] = surname(p["name"])
    if "clock" in p and key != "score":
        p["clock"] = minute_phrase(str(p["clock"]), lang)
    if "dist" in p:
        # football units: yards in English, metres elsewhere; shots get a landmark
        # ("from the edge of the box") computed from where the ball was struck
        p["yd"] = units.yards(p["dist"])
        p["dist"] = round(float(p["dist"]))
        p["where"] = units.shot_where(p["dist"], p.get("x"), p.get("y"), lang)
    if "v" in p and key == "m_speed":
        p["kmh"] = p.get("kmh") or units.kmh(p["v"])
    if key == "score":
        p["when"] = when_phrase(str(p["clock"]), lang)
        hg, ag = int(p["hg"]), int(p["ag"])
        if hg == ag:
            key = "score_draw"
        else:
            p["leader"] = p["home"] if hg > ag else p["away"]
            if ag > hg:
                p["hg"], p["ag"] = ag, hg
    elif key == "m_goal" or key == "m_chance":
        p["xgw"] = xg_word(float(p["xg"]), lang)
        if "outcome" in p:
            p["outcome"] = OUTCOME[lang].get(p["outcome"], p["outcome"])
    elif key == "m_stop":
        p["act"] = ACT[lang][p["action"]]
        p["dw"] = danger_word(float(p["d"]), lang)
    elif key == "team_shots":
        per = float(p["xg"]) / max(1, int(p["shots"]))
        p["quality"] = QUALITY[lang][0 if per < 0.08 else 1 if per < 0.14 else 2]
    pats = P.get(key)
    if not pats:
        return None
    variants = pats.get(lang) or pats["en"]
    try:
        text = _pick(variants, fact["id"] + mode + lang).format(**p)
    except KeyError:
        return None
    text = text[0].upper() + text[1:]
    return f"{text} [{fact['id']}]."


def connective(key: str, lang: str, seed: str, **params) -> str:
    variants = P[key].get(lang) or P[key]["en"]
    return _pick(variants, seed).format(**params)


# --------------------------------------------------------------------------- the narrator
def narrate(req) -> str:
    """Template narrator in the pundit voice. Same contract as before: every
    sentence cites a fact id; numbers and names come only from cited facts."""
    from shield.engine import i18n
    lang = req.language if req.language in i18n.LANGS else "en"
    facts = req.packet["facts"]
    mode = req.mode
    by_tag = lambda tag: [f for f in facts if tag in f["tags"]]
    out: list[str] = []

    def say(f):
        s = render(f, lang, mode)
        if s:
            out.append(s)

    focus = req.player_focus
    pf = [f for f in facts if f.get("player") == focus] if focus else []
    if mode in ("player", "kid") and pf:
        fp = req.packet.get("player_focus") or {}
        nm = fp.get("name", "")
        ordered = sorted(pf, key=lambda f: (0 if "moment" in f["tags"] else 1 if "defence" in f["tags"] or "attack" in f["tags"] else 2))
        seen_keys = set()
        for f in ordered:
            if f["key"] in seen_keys or f["key"] == "physical":
                continue
            seen_keys.add(f["key"])
            say(f)
            if len(out) >= (4 if mode == "kid" else 5):
                break
        if mode == "kid" and fp and pf:
            hht = fp.get("how_he_thinks", {})
            faw = hht.get("first_action_after_winning_ball", {})
            fid = pf[0]["id"]
            if faw:
                top = max(faw.items(), key=lambda kv: kv[1])
                out.append(connective("thinks", lang, fid + "thinks", s=surname(nm), dir=DIR[lang].get(top[0], top[0])) + f" [{fid}].")
            strengths = fp.get("strengths", [])
            weak = fp.get("weaknesses", [])
            if strengths:
                out.append(connective("best", lang, fid + "best", m=skill(strengths[0]["metric"], lang)) + f" [{fid}].")
            if weak:
                out.append(connective("work", lang, fid + "work", m=skill(weak[0]["metric"], lang)) + f" [{fid}].")
            out.append(connective("drill", lang, fid + "drill") + f" [{fid}].")
    elif mode == "overlay":
        m = by_tag("moment")
        if m:
            s = render(m[0], lang, mode)
            return s or f"{m[0]['text']} [{m[0]['id']}]."
    else:
        score = by_tag("score")
        if score:
            say(score[0])
        moments = by_tag("moment")
        players = [f for f in facts if "moment" not in f["tags"] and "score" not in f["tags"] and f.get("player")]
        players.sort(key=lambda f: -(float(f["value"]) if isinstance(f["value"], (int, float)) else 0)
                     * (3 if "goals" in f["tags"] else 0.1 if "physical" in f["tags"] else 1))
        if mode == "casual":
            goal = [f for f in moments if "goal" in f["tags"]][:1]
            for f in goal:
                say(f)
            ended = [f for f in facts if "attacks_ended" in f["tags"]]
            if ended:
                say(max(ended, key=lambda f: f["value"]))
            tps = [f for f in facts if "threat_prevented" in f["tags"]]
            stop = max(tps, key=lambda f: f["value"]) if tps else None
            if stop:
                sc = req.packet.get("match", {}).get("score", {})
                total = int(sc.get("home", 0)) + int(sc.get("away", 0))
                wkey = "why_nogoal" if total == 0 else "why" if total == 1 else "why_many"
                out.append(connective(wkey, lang, stop["id"] + "why", name=stop["params"]["name"]) + f" [{stop['id']}].")
        else:
            n = 7
            picked_keys = set()
            for f in moments[:4] + players:
                if len(out) >= n:
                    break
                if f["key"] in picked_keys and f["key"] not in ("m_stop", "m_key_pass", "m_chance"):
                    continue
                picked_keys.add(f["key"])
                say(f)
            rhythm = by_tag("rhythm")
            if rhythm and len(out) < n + 1:
                say(rhythm[0])
    text = " ".join(out) if out else "No facts yet. [f0]"
    text = surnames_after_first(text, list(getattr(req, "roster", []) or []))
    if lang == "fr":
        text = re.sub(r"\b(d|qu|l|n|j|m|s|c)e ([AEIOUÉÈÊÀÂÎÔÛaeiouéèêàâîôûhH])", r"\1'\2", text)
    return text
