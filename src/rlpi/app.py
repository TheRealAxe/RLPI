"""Petite application RLPI : réglages (profil, clé ballchasing, dossier des replays) et analyse en un clic.

    python -m rlpi.app        (ou le raccourci « RLPI » créé par « Installer RLPI.cmd »)

Les réglages sont enregistrés dans .env à la racine du projet. L'analyse enchaîne les mêmes étapes que le
README, chacune dans un processus séparé, et affiche leur sortie dans la fenêtre.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from collections import Counter
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from rlpi.config import FRAMES, ROOT, SOURCE

ENV = ROOT / ".env"
DASHBOARD = ROOT / "reports" / "tableau_de_bord.html"
DEFAULT_DEMOS = Path.home() / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Demos"
KEYS = ["BALLCHASING_TOKEN", "RLPI_PLAYER", "RLPI_COMPARE", "RLPI_DEMOS", "RLPI_SINCE"]


def read_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


def write_env(new: dict[str, str]) -> None:
    """Met à jour .env en gardant les commentaires et les autres clés."""
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in new:
                lines[i] = f"{k}={new[k]}"
                seen.add(k)
    lines += [f"{k}={v}" for k, v in new.items() if k not in seen]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def players_in_games() -> list[tuple[str, str, int]]:
    """Joueurs vus dans tes parties analysées : (identifiant, pseudo, nombre de parties), le plus fréquent d'abord."""
    count: Counter[str] = Counter()
    names: dict[str, str] = {}
    for f in (FRAMES / SOURCE).glob("*.meta.json"):
        try:
            for p in json.loads(f.read_text(encoding="utf-8")).get("players", []):
                count[p["id"]] += 1
                names[p["id"]] = p.get("name", "")
        except Exception:  # noqa: BLE001 — fichier illisible : on l'ignore
            continue
    return [(pid, names[pid], n) for pid, n in count.most_common()]


def steps(demos: str, since: str) -> list[tuple[str, list[str]]]:
    dash = ["dashboard"] + (["--since", since] if since else [])
    return [
        ("Lecture des replays", ["frames", "--source", SOURCE, "--dir", demos]),
        ("Statistiques de base", ["stats", "--source", SOURCE, "--dir", demos, "--online-3v3"]),
        ("PROFIL", []),  # détection du joueur si le profil est vide
        ("Valeur des touches", ["value", "touches", "--source", SOURCE, "--horizon", "5"]),
        ("Décisions à la touche", ["decisions", "touches-perso"]),
        ("Placement", ["decisions", "placement-score", "--source", SOURCE]),
        ("Passes", ["passes"]),
        ("Buts", ["value", "goals", "--source", SOURCE]),
        ("Indice de performance", ["perf"]),
        ("Défense", ["defense", "--source", SOURCE]),
        ("Tableau de bord", dash),
        ("Meilleur jeu", ["bestplay", "extract", "--source", SOURCE]),
        ("Actions à revoir", ["bestplay", "worst", "--games", "10", "--k", "5"]),
        ("Page des modèles", ["models_page"]),
    ]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RLPI — Rocket League Player Index")
        self.geometry("760x620")
        self.minsize(640, 520)
        self.q: queue.Queue = queue.Queue()
        self.running = False
        env = read_env()

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Réglages", font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")

        self.v_demos = tk.StringVar(value=env.get("RLPI_DEMOS") or (str(DEFAULT_DEMOS) if DEFAULT_DEMOS.exists() else ""))
        self.v_player = tk.StringVar(value=env.get("RLPI_PLAYER", ""))
        self.v_compare = tk.StringVar(value=env.get("RLPI_COMPARE", ""))
        self.v_token = tk.StringVar(value=env.get("BALLCHASING_TOKEN", ""))
        self.v_since = tk.StringVar(value=env.get("RLPI_SINCE", ""))

        r = 1
        ttk.Label(frm, text="Dossier des replays").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_demos).grid(row=r, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Parcourir…", command=self.pick_dir).grid(row=r, column=2, sticky="ew")

        r += 1
        ttk.Label(frm, text="Mon profil").grid(row=r, column=0, sticky="w", pady=4)
        self.cb_player = ttk.Combobox(frm, textvariable=self.v_player)
        self.cb_player.grid(row=r, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Détecter", command=self.detect).grid(row=r, column=2, sticky="ew")
        r += 1
        ttk.Label(frm, text="Identifiant (Steam:…, Epic:…) ou pseudo exact. Laisse vide : il sera détecté "
                            "à la première analyse.", foreground="#666").grid(row=r, column=1, columnspan=2, sticky="w", padx=6)

        r += 1
        ttk.Label(frm, text="Coéquipiers à comparer").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_compare).grid(row=r, column=1, columnspan=2, sticky="ew", padx=(6, 0))
        r += 1
        ttk.Label(frm, text="Pseudos ou identifiants séparés par des virgules (facultatif).",
                  foreground="#666").grid(row=r, column=1, columnspan=2, sticky="w", padx=6)

        r += 1
        ttk.Label(frm, text="Parties à partir du").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(frm, textvariable=self.v_since, width=14).grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(frm, text="AAAA-MM-JJ, facultatif : vide = toutes les parties.",
                  foreground="#666").grid(row=r, column=1, columnspan=2, sticky="w", padx=6)

        r += 1
        ttk.Label(frm, text="Clé API ballchasing").grid(row=r, column=0, sticky="w", pady=4)
        self.e_token = ttk.Entry(frm, textvariable=self.v_token, show="•")
        self.e_token.grid(row=r, column=1, sticky="ew", padx=6)
        self.show_tok = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="Afficher", variable=self.show_tok,
                        command=lambda: self.e_token.config(show="" if self.show_tok.get() else "•")).grid(row=r, column=2, sticky="w")
        r += 1
        ttk.Label(frm, text="Facultatif : seulement pour télécharger des replays pros ou envoyer les tiens.",
                  foreground="#666").grid(row=r, column=1, columnspan=2, sticky="w", padx=6)

        r += 1
        bar = ttk.Frame(frm)
        bar.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(14, 6))
        ttk.Button(bar, text="Enregistrer", command=self.save).pack(side="left")
        self.b_run = ttk.Button(bar, text="Analyser mes parties", command=self.run)
        self.b_run.pack(side="left", padx=8)
        ttk.Button(bar, text="Ouvrir le tableau de bord", command=self.open_dashboard).pack(side="left")

        r += 1
        self.v_status = tk.StringVar(value="Prêt.")
        ttk.Label(frm, textvariable=self.v_status).grid(row=r, column=0, columnspan=3, sticky="w")
        r += 1
        self.pb = ttk.Progressbar(frm, mode="determinate")
        self.pb.grid(row=r, column=0, columnspan=3, sticky="ew", pady=4)

        r += 1
        frm.rowconfigure(r, weight=1)
        logf = ttk.Frame(frm)
        logf.grid(row=r, column=0, columnspan=3, sticky="nsew")
        self.log = tk.Text(logf, height=12, wrap="word", font=("Consolas", 9), state="disabled")
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.config(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.detect(quiet=True)
        self.after(100, self.poll)

    # ---- réglages ----
    def values(self) -> dict[str, str]:
        player = self.v_player.get().strip()
        if "  (" in player:  # entrée de la liste « id  (pseudo, n parties) »
            player = player.split("  (")[0]
        return {"BALLCHASING_TOKEN": self.v_token.get().strip(), "RLPI_PLAYER": player,
                "RLPI_COMPARE": self.v_compare.get().strip(), "RLPI_DEMOS": self.v_demos.get().strip(),
                "RLPI_SINCE": self.v_since.get().strip()}

    def save(self, quiet: bool = False) -> None:
        vals = self.values()
        self.v_player.set(vals["RLPI_PLAYER"])
        write_env(vals)
        if not quiet:
            self.v_status.set("Réglages enregistrés.")

    def pick_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.v_demos.get() or str(Path.home()), title="Dossier des replays")
        if d:
            self.v_demos.set(str(Path(d)))

    def detect(self, quiet: bool = False) -> None:
        ps = players_in_games()
        self.cb_player["values"] = [f"{pid}  ({name}, {n} parties)" for pid, name, n in ps[:12]]
        if not ps:
            if not quiet:
                messagebox.showinfo("RLPI", "Aucune partie analysée pour l'instant. Lance « Analyser mes parties » : "
                                            "ton profil sera détecté après la lecture des replays.")
            return
        if not self.v_player.get().strip():
            self.v_player.set(ps[0][0])
        if not quiet:
            self.cb_player.event_generate("<Down>")

    def open_dashboard(self) -> None:
        if DASHBOARD.exists():
            webbrowser.open(DASHBOARD.as_uri())
        else:
            messagebox.showinfo("RLPI", "Pas encore de tableau de bord : lance d'abord « Analyser mes parties ».")

    # ---- analyse ----
    def run(self) -> None:
        if self.running:
            return
        vals = self.values()
        if not vals["RLPI_DEMOS"] or not Path(vals["RLPI_DEMOS"]).is_dir():
            messagebox.showerror("RLPI", "Choisis le dossier de tes replays (en général Documents\\My Games\\"
                                         "Rocket League\\TAGame\\Demos).")
            return
        self.save(quiet=True)
        self.running = True
        self.b_run.state(["disabled"])
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")
        threading.Thread(target=self.worker, args=(vals,), daemon=True).start()

    def worker(self, vals: dict[str, str]) -> None:
        py = Path(sys.executable)
        if py.name.lower() == "pythonw.exe":
            py = py.with_name("python.exe")
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONPATH=str(ROOT / "src"))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        todo = steps(vals["RLPI_DEMOS"], vals["RLPI_SINCE"])
        for k, (label, args) in enumerate(todo):
            self.q.put(("step", k, len(todo), label))
            if label == "PROFIL":
                if not vals["RLPI_PLAYER"]:
                    ps = players_in_games()
                    if not ps:
                        self.q.put(("fail", "Aucune partie 3v3 trouvée dans ce dossier."))
                        return
                    vals["RLPI_PLAYER"] = ps[0][0]
                    self.q.put(("player", ps[0][0], ps[0][1], ps[0][2]))
                continue
            env.update({k2: vals[k2] for k2 in KEYS})
            self.q.put(("log", f"\n▶ {label}\n"))
            proc = subprocess.Popen([str(py), "-m", f"rlpi.{args[0]}", *args[1:]], cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
            tail: list[str] = []
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace")
                tail = (tail + [line])[-15:]
                self.q.put(("log", line))
            if proc.wait() != 0:
                self.q.put(("fail", f"Échec à l'étape « {label} ». Détail dans le journal ci-dessous."))
                return
        self.q.put(("done",))

    def poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", msg[1])
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif kind == "step":
                    _, k, n, label = msg
                    self.pb.config(maximum=n, value=k)
                    if label != "PROFIL":
                        self.v_status.set(f"Étape {k + 1}/{n} : {label}…")
                elif kind == "player":
                    _, pid, name, n = msg
                    self.v_player.set(pid)
                    self.save(quiet=True)
                    self.detect(quiet=True)
                    self.q.put(("log", f"\nProfil détecté : {name} ({pid}), présent dans {n} parties. "
                                       "Tu peux le changer dans « Mon profil ».\n"))
                elif kind == "fail":
                    self.finish(msg[1], ok=False)
                elif kind == "done":
                    self.pb.config(value=self.pb["maximum"])
                    self.finish("Analyse terminée.", ok=True)
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def finish(self, text: str, ok: bool) -> None:
        self.running = False
        self.b_run.state(["!disabled"])
        self.v_status.set(text)
        if ok:
            if messagebox.askyesno("RLPI", "Analyse terminée. Ouvrir le tableau de bord ?"):
                self.open_dashboard()
        else:
            messagebox.showerror("RLPI", text)


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
