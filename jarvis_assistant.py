from __future__ import annotations

import base64
import json
import os
import platform
import random
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from urllib.parse import quote_plus


DATA_FILE = Path(__file__).with_name("jarvis_data.json")


@dataclass
class Note:
    text: str
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    @classmethod
    def from_dict(cls, data: dict) -> "Note":
        return cls(
            text=str(data.get("text", "")).strip(),
            created_at=str(
                data.get("created_at", datetime.now().isoformat(timespec="seconds"))
            ),
        )


@dataclass
class Reminder:
    id: str
    text: str
    due_at: str
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    fired: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "Reminder":
        return cls(
            id=str(data.get("id", datetime.now().strftime("%Y%m%d%H%M%S%f"))),
            text=str(data.get("text", "")).strip(),
            due_at=str(data.get("due_at", "")),
            created_at=str(
                data.get("created_at", datetime.now().isoformat(timespec="seconds"))
            ),
            fired=bool(data.get("fired", False)),
        )

    @property
    def due_datetime(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.due_at)
        except ValueError:
            return None


class JarvisStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.notes: list[Note] = []
        self.reminders: list[Reminder] = []

    def load(self) -> None:
        if not self.path.exists():
            return

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.notes = []
            self.reminders = []
            return

        self.notes = [
            note
            for note in (Note.from_dict(item) for item in payload.get("notes", []))
            if note.text
        ]
        self.reminders = [
            reminder
            for reminder in (
                Reminder.from_dict(item) for item in payload.get("reminders", [])
            )
            if reminder.text and reminder.due_datetime
        ]

    def save(self) -> None:
        payload = {
            "notes": [asdict(note) for note in self.notes],
            "reminders": [asdict(reminder) for reminder in self.reminders],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def add_note(self, text: str) -> None:
        self.notes.append(Note(text=text))
        self.save()

    def clear_notes(self) -> int:
        count = len(self.notes)
        self.notes = []
        self.save()
        return count

    def add_reminder(self, text: str, due_at: datetime) -> Reminder:
        reminder = Reminder(
            id=datetime.now().strftime("%Y%m%d%H%M%S%f"),
            text=text,
            due_at=due_at.isoformat(timespec="seconds"),
        )
        self.reminders.append(reminder)
        self.save()
        return reminder

    def clear_completed_reminders(self) -> int:
        before = len(self.reminders)
        self.reminders = [reminder for reminder in self.reminders if not reminder.fired]
        self.save()
        return before - len(self.reminders)


class Speaker:
    def __init__(self) -> None:
        self._pyttsx3 = None
        try:
            import pyttsx3  # type: ignore

            self._pyttsx3 = pyttsx3
        except ImportError:
            self._pyttsx3 = None

    @property
    def available(self) -> bool:
        return self._pyttsx3 is not None or sys.platform.startswith("win")

    def speak(self, text: str) -> None:
        if not self.available:
            return
        threading.Thread(target=self._speak_blocking, args=(text,), daemon=True).start()

    def _speak_blocking(self, text: str) -> None:
        if self._pyttsx3 is not None:
            try:
                engine = self._pyttsx3.init()
                engine.setProperty("rate", 170)
                engine.say(text)
                engine.runAndWait()
                return
            except Exception:
                pass

        if sys.platform.startswith("win"):
            script = (
                "Add-Type -AssemblyName System.Speech\n"
                "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "$speaker.Rate = 0\n"
                "$speaker.Volume = 100\n"
                f"$speaker.Speak({json.dumps(text)})\n"
            )
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            try:
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-EncodedCommand", encoded],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                return


class AssistantEngine:
    APP_COMMANDS = {
        "notepad": ["notepad"],
        "calculator": ["calc"],
        "calc": ["calc"],
        "paint": ["mspaint"],
        "explorer": ["explorer"],
        "file explorer": ["explorer"],
        "command prompt": ["cmd"],
        "cmd": ["cmd"],
        "powershell": ["powershell"],
    }

    JOKES = (
        "I told my computer I needed a break, and it said no problem, it would go to sleep.",
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "I would tell you a UDP joke, but you might not get it.",
        "There are only 10 kinds of people: those who understand binary and those who do not.",
    )

    HELP_LINES = (
        "Try: open notepad",
        "Try: search Python tkinter tutorial",
        "Try: remind me to drink water in 15 minutes",
        "Try: remind me to call Alex at 6:30 pm",
        "Try: note buy printer ink",
        "Try: list notes",
        "Try: system info",
        "Try: tell me a joke",
    )

    def __init__(self, store: JarvisStore) -> None:
        self.store = store

    def respond(self, command: str) -> str:
        original = command.strip()
        cleaned_original = self._strip_invocation(original)
        normalized = self._normalize(original)

        if not normalized:
            return "I am listening. Type a command when you are ready."

        if normalized in {"help", "what can you do", "commands", "show commands"}:
            return "Here are a few things I can do:\n" + "\n".join(self.HELP_LINES)

        if re.search(r"\b(hello|hi|hey|namaste)\b", normalized):
            return random.choice(
                (
                    "Hello. Jarvis is online.",
                    "Hi there. Ready when you are.",
                    "At your service. What are we handling?",
                )
            )

        if normalized in {"time", "what time is it", "current time"}:
            return f"The time is {datetime.now().strftime('%I:%M %p')}."

        if normalized in {"date", "today", "what is the date", "current date"}:
            return f"Today is {datetime.now().strftime('%A, %d %B %Y')}."

        if "joke" in normalized:
            return random.choice(self.JOKES)

        if normalized in {"system info", "about system", "computer info"}:
            return self._system_info()

        if normalized.startswith(("search ", "google ")):
            query = re.sub(r"^(search|google)\s+", "", cleaned_original, flags=re.I).strip()
            return self._search_web(query)

        if normalized.startswith("youtube "):
            query = re.sub(r"^youtube\s+", "", cleaned_original, flags=re.I).strip()
            return self._open_url(
                f"https://www.youtube.com/results?search_query={quote_plus(query)}",
                f"Searching YouTube for {query}.",
            )

        if normalized.startswith(("open ", "launch ", "start ")):
            target = re.sub(
                r"^(open|launch|start)\s+", "", cleaned_original, flags=re.I
            ).strip()
            return self._open_target(target)

        if normalized.startswith(("note ", "remember ")):
            text = re.sub(r"^(note|remember)\s+", "", cleaned_original, flags=re.I).strip()
            return self._add_note(text)

        if normalized in {"list notes", "show notes", "notes"}:
            return self._list_notes()

        if normalized in {"clear notes", "delete notes"}:
            count = self.store.clear_notes()
            return f"Cleared {count} note(s)."

        if normalized.startswith("remind "):
            return self._add_reminder(cleaned_original)

        if normalized in {"list reminders", "show reminders", "reminders"}:
            return self._list_reminders()

        if normalized in {"clear completed reminders", "clear reminders"}:
            count = self.store.clear_completed_reminders()
            return f"Cleared {count} completed reminder(s)."

        if normalized in {"who are you", "what are you"}:
            return "I am Jarvis, a local desktop assistant for quick commands, notes, reminders, and web launches."

        return (
            "I did not understand that command yet. Type 'help' for examples, "
            "or try opening an app, searching the web, taking a note, or setting a reminder."
        )

    def _normalize(self, text: str) -> str:
        normalized = text.lower().strip()
        normalized = re.sub(r"\b(jarvis|please|can you|could you)\b", "", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip(" ?.!").strip()

    def _strip_invocation(self, text: str) -> str:
        cleaned = re.sub(r"\b(jarvis|please|can you|could you)\b", "", text, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" ,?!.").strip()

    def _system_info(self) -> str:
        user = os.getenv("USERNAME") or os.getenv("USER") or "unknown user"
        return (
            f"User: {user}\n"
            f"OS: {platform.system()} {platform.release()}\n"
            f"Machine: {platform.machine()}\n"
            f"Python: {platform.python_version()}"
        )

    def _search_web(self, query: str) -> str:
        if not query:
            return "What would you like me to search for?"
        return self._open_url(
            f"https://www.google.com/search?q={quote_plus(query)}",
            f"Searching the web for {query}.",
        )

    def _open_url(self, url: str, response: str) -> str:
        webbrowser.open(url)
        return response

    def _open_target(self, target: str) -> str:
        normalized = self._normalize(target)
        if not normalized:
            return "What should I open?"

        if normalized in {"browser", "web", "google", "chrome"}:
            return self._open_url("https://www.google.com", "Opening your browser.")

        if normalized in {"youtube"}:
            return self._open_url("https://www.youtube.com", "Opening YouTube.")

        if normalized in {"gmail", "mail"}:
            return self._open_url("https://mail.google.com", "Opening Gmail.")

        if normalized in {"settings", "windows settings"} and sys.platform.startswith("win"):
            try:
                os.startfile("ms-settings:")  # type: ignore[attr-defined]
                return "Opening Windows Settings."
            except OSError:
                return "I could not open Windows Settings."

        if self._looks_like_url(target):
            url = target if re.match(r"^https?://", target, re.I) else f"https://{target}"
            return self._open_url(url, f"Opening {target}.")

        command = self.APP_COMMANDS.get(normalized)
        if command:
            try:
                subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return f"Opening {target}."
            except OSError as error:
                return f"I could not open {target}: {error}"

        return self._search_web(target)

    def _looks_like_url(self, target: str) -> bool:
        return bool(re.match(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/.*)?$", target.strip(), re.I))

    def _add_note(self, text: str) -> str:
        if not text:
            return "What should I note?"
        self.store.add_note(text)
        return "Noted."

    def _list_notes(self) -> str:
        if not self.store.notes:
            return "You do not have any notes yet."

        lines = ["Your notes:"]
        for index, note in enumerate(self.store.notes[-10:], start=1):
            created = self._format_datetime(note.created_at)
            lines.append(f"{index}. {note.text} ({created})")
        return "\n".join(lines)

    def _add_reminder(self, command: str) -> str:
        parsed = self._parse_reminder(command)
        if parsed is None:
            return (
                "I could not read that reminder. Try: "
                "'remind me to drink water in 15 minutes' or "
                "'remind me to call Alex at 6:30 pm'."
            )

        text, due_at = parsed
        reminder = self.store.add_reminder(text, due_at)
        return f"Reminder set for {self._format_datetime(reminder.due_at)}: {reminder.text}"

    def _parse_reminder(self, command: str) -> tuple[str, datetime] | None:
        cleaned = re.sub(r"^remind\s+(me\s+)?(to\s+)?", "", command.strip(), flags=re.I)

        relative = re.match(
            r"(?P<text>.+?)\s+in\s+(?P<amount>\d+)\s+"
            r"(?P<unit>second|seconds|minute|minutes|hour|hours|day|days)$",
            cleaned,
            re.I,
        )
        if relative:
            amount = int(relative.group("amount"))
            unit = relative.group("unit").lower()
            kwargs = {}
            if unit.startswith("second"):
                kwargs["seconds"] = amount
            elif unit.startswith("minute"):
                kwargs["minutes"] = amount
            elif unit.startswith("hour"):
                kwargs["hours"] = amount
            else:
                kwargs["days"] = amount
            return relative.group("text").strip(), datetime.now() + timedelta(**kwargs)

        absolute = re.match(
            r"(?P<text>.+?)\s+at\s+(?P<hour>\d{1,2})"
            r"(?::(?P<minute>\d{2}))?\s*(?P<period>am|pm)?$",
            cleaned,
            re.I,
        )
        if absolute:
            text = absolute.group("text").strip()
            hour = int(absolute.group("hour"))
            minute = int(absolute.group("minute") or "0")
            period = (absolute.group("period") or "").lower()

            if period == "pm" and hour != 12:
                hour += 12
            if period == "am" and hour == 12:
                hour = 0
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None

            due_at = datetime.now().replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if due_at <= datetime.now():
                due_at += timedelta(days=1)
            return text, due_at

        return None

    def _list_reminders(self) -> str:
        active = [reminder for reminder in self.store.reminders if not reminder.fired]
        if not active:
            return "You do not have any active reminders."

        lines = ["Active reminders:"]
        for index, reminder in enumerate(active, start=1):
            lines.append(
                f"{index}. {reminder.text} - {self._format_datetime(reminder.due_at)}"
            )
        return "\n".join(lines)

    def _format_datetime(self, iso_value: str) -> str:
        try:
            value = datetime.fromisoformat(iso_value)
        except ValueError:
            return iso_value
        return value.strftime("%d %b %Y, %I:%M %p")


class JarvisApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Jarvis Desktop Assistant")
        self.geometry("860x620")
        self.minsize(720, 500)

        self.store = JarvisStore(DATA_FILE)
        self.store.load()
        self.engine = AssistantEngine(self.store)
        self.speaker = Speaker()
        self.voice_enabled = tk.BooleanVar(value=self.speaker.available)
        self.input_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Jarvis is online.")
        self.recognizer = None

        self._configure_style()
        self._build_ui()
        self._setup_voice_input()
        self._bind_events()
        self._greet()
        self._check_reminders()

    def _configure_style(self) -> None:
        self.configure(background="#eef2f6")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef2f6")
        style.configure(
            "Header.TLabel",
            background="#eef2f6",
            foreground="#111827",
            font=("Segoe UI", 22, "bold"),
        )
        style.configure(
            "Subtle.TLabel",
            background="#eef2f6",
            foreground="#4b5563",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Status.TLabel",
            background="#dbe5ef",
            foreground="#1f2937",
            font=("Segoe UI", 10),
        )
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        shell = ttk.Frame(self, padding=18)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Jarvis Desktop Assistant", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="Local commands, notes, reminders, app launching, and web search.",
            style="Subtle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        voice_toggle = ttk.Checkbutton(
            header,
            text="Voice replies",
            variable=self.voice_enabled,
            state=tk.NORMAL if self.speaker.available else tk.DISABLED,
        )
        voice_toggle.grid(row=0, column=1, sticky="e")

        content = ttk.Frame(shell)
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        self.chat = scrolledtext.ScrolledText(
            content,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            borderwidth=1,
            relief=tk.SOLID,
            padx=12,
            pady=12,
            state=tk.DISABLED,
        )
        self.chat.grid(row=0, column=0, sticky="nsew")
        self.chat.tag_configure("user", foreground="#1d4ed8", font=("Segoe UI", 10, "bold"))
        self.chat.tag_configure(
            "assistant", foreground="#065f46", font=("Segoe UI", 10, "bold")
        )
        self.chat.tag_configure("system", foreground="#6b7280", font=("Segoe UI", 9, "italic"))

        examples = ttk.Frame(content, padding=(14, 0, 0, 0))
        examples.grid(row=0, column=1, sticky="ns")
        ttk.Label(examples, text="Quick commands", style="Subtle.TLabel").pack(anchor="w")
        self.command_list = tk.Listbox(
            examples,
            height=12,
            width=32,
            activestyle="none",
            font=("Segoe UI", 10),
            borderwidth=1,
            relief=tk.SOLID,
        )
        for command in AssistantEngine.HELP_LINES:
            self.command_list.insert(tk.END, command.replace("Try: ", ""))
        self.command_list.pack(fill=tk.Y, expand=False, pady=(6, 0))
        self.command_list.bind("<Double-Button-1>", self._use_selected_example)

        composer = ttk.Frame(shell)
        composer.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        composer.columnconfigure(0, weight=1)

        self.input_entry = ttk.Entry(
            composer,
            textvariable=self.input_var,
            font=("Segoe UI", 11),
        )
        self.input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input_entry.focus_set()

        self.listen_button = ttk.Button(
            composer,
            text="Listen",
            command=self.listen_once,
        )
        self.listen_button.grid(row=0, column=1, padx=(0, 8))

        ttk.Button(
            composer,
            text="Send",
            command=self.send_command,
            style="Accent.TButton",
        ).grid(row=0, column=2)

        ttk.Label(shell, textvariable=self.status_var, style="Status.TLabel", padding=8).grid(
            row=3, column=0, sticky="ew", pady=(12, 0)
        )

    def _setup_voice_input(self) -> None:
        try:
            import speech_recognition as sr  # type: ignore

            self.recognizer = sr.Recognizer()
            self.microphone_class = sr.Microphone
        except ImportError:
            self.recognizer = None
            self.microphone_class = None
            self.listen_button.configure(state=tk.DISABLED)
            self.status_var.set(
                "Text mode is ready. Voice input needs SpeechRecognition and PyAudio."
            )

    def _bind_events(self) -> None:
        self.bind("<Return>", lambda _event: self.send_command())
        self.bind("<Escape>", lambda _event: self.input_var.set(""))

    def _greet(self) -> None:
        self._append("System", "Jarvis started. Type 'help' for command examples.", "system")
        self._assistant_reply("Hello. Jarvis is online.")

    def _append(self, speaker: str, text: str, tag: str) -> None:
        self.chat.configure(state=tk.NORMAL)
        self.chat.insert(tk.END, f"{speaker}: ", tag)
        self.chat.insert(tk.END, f"{text}\n\n")
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)

    def _assistant_reply(self, text: str) -> None:
        self._append("Jarvis", text, "assistant")
        if self.voice_enabled.get():
            self.speaker.speak(self._speech_text(text))

    def _speech_text(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", text)
        return compact[:400]

    def send_command(self) -> None:
        command = self.input_var.get().strip()
        if not command:
            return
        self.input_var.set("")
        self._append("You", command, "user")
        response = self.engine.respond(command)
        self._assistant_reply(response)
        self.status_var.set(f"Last command: {datetime.now().strftime('%I:%M:%S %p')}")

    def listen_once(self) -> None:
        if not self.recognizer or not self.microphone_class:
            messagebox.showinfo(
                "Voice input unavailable",
                "Install SpeechRecognition and PyAudio to use microphone commands.",
            )
            return

        self.listen_button.configure(state=tk.DISABLED)
        self.status_var.set("Listening...")
        threading.Thread(target=self._listen_worker, daemon=True).start()

    def _listen_worker(self) -> None:
        try:
            with self.microphone_class() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=8)
            text = self.recognizer.recognize_google(audio)
        except Exception as error:
            self.after(
                0,
                lambda: self._voice_error(f"Could not understand voice input: {error}"),
            )
            return

        self.after(0, lambda: self._voice_success(text))

    def _voice_success(self, text: str) -> None:
        self.listen_button.configure(state=tk.NORMAL)
        self.status_var.set("Voice command captured.")
        self.input_var.set(text)
        self.send_command()

    def _voice_error(self, message: str) -> None:
        self.listen_button.configure(state=tk.NORMAL)
        self.status_var.set(message)

    def _use_selected_example(self, _event: tk.Event) -> None:
        selection = self.command_list.curselection()
        if not selection:
            return
        self.input_var.set(self.command_list.get(selection[0]))
        self.input_entry.focus_set()
        self.input_entry.icursor(tk.END)

    def _check_reminders(self) -> None:
        now = datetime.now()
        changed = False
        for reminder in self.store.reminders:
            due_at = reminder.due_datetime
            if reminder.fired or due_at is None or due_at > now:
                continue
            reminder.fired = True
            changed = True
            message = f"Reminder: {reminder.text}"
            self._assistant_reply(message)
            messagebox.showinfo("Jarvis Reminder", reminder.text)

        if changed:
            self.store.save()
        self.after(10_000, self._check_reminders)


def main() -> None:
    app = JarvisApp()
    app.mainloop()


if __name__ == "__main__":
    main()
