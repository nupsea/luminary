"""Conversation-aware chunking for speaker-formatted text (S56).

ConversationChunker handles three common conversation formats:
  A: Timestamp prefix  — [HH:MM] Speaker: message
  B: Capitalized name colon — Alice: message
  C: Name arrow — Alice> message

Chunks are formed by grouping consecutive same-speaker turns and accumulating
until ~450 estimated tokens (len // 4), with 20% overlap (last turn of previous
chunk prepended to next).
"""

import re
from dataclasses import dataclass, field


@dataclass
class ConversationChunk:
    text: str
    speaker: str
    turn_index: int  # index of first turn in this chunk


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_PAT_TIMESTAMP = re.compile(r"^\[?\d{1,2}[:/]\d{2}")
_PAT_NAME_COLON = re.compile(r"^[A-Z][a-zA-Z .]+:\s")
_PAT_NAME_ARROW = re.compile(r"^[A-Z][a-zA-Z .]+>\s")

_SPEAKER_COLON = re.compile(r"^([A-Z][a-zA-Z .]+):\s+(.*)")
_SPEAKER_ARROW = re.compile(r"^([A-Z][a-zA-Z .]+)>\s+(.*)")
# Timestamp lines: optional [DD/MM/YYYY, HH:MM] prefix then speaker
_SPEAKER_TIMESTAMP = re.compile(
    r"^\[?\d{1,2}[:/]\d{2}.*?\]?\s*([A-Z][a-zA-Z .]+):\s+(.*)"
)

_MAX_TOKENS = 450
_OVERLAP_TURNS = 1  # number of turns carried over as overlap


@dataclass
class _Turn:
    speaker: str
    text: str  # "Speaker: message" verbatim
    turn_index: int
    lines: list[str] = field(default_factory=list)


class ConversationChunker:
    """Detect and chunk speaker-format conversation text."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, text: str) -> bool:
        """Return True if text looks like a speaker-format conversation.

        Checks the first 60 lines for >= 5 matches with any pattern.
        """
        lines = text.splitlines()[:60]
        matches = sum(
            1
            for line in lines
            if _PAT_TIMESTAMP.match(line)
            or _PAT_NAME_COLON.match(line)
            or _PAT_NAME_ARROW.match(line)
        )
        return matches >= 5

    def chunk(self, text: str) -> list[ConversationChunk]:
        """Parse text into ConversationChunks respecting speaker turns."""
        turns = self._parse_turns(text)
        if not turns:
            return []
        return self._build_chunks(turns)

    # ------------------------------------------------------------------
    # Roster / timeline extraction
    # ------------------------------------------------------------------

    def extract_roster(self, chunks: list[ConversationChunk]) -> dict:
        """Count speaker turns by parsing chunk texts and return roster metadata.

        Each "Speaker: " line prefix within chunk text counts as one turn.
        Overlap lines (carried from previous chunk) may be counted twice, but
        the error is at most _OVERLAP_TURNS * num_chunks — acceptable for roster display.
        """
        speaker_turns: dict[str, int] = {}
        # Count every speaker-attributed line within all chunks
        for chunk in chunks:
            current_speaker: str | None = None
            for line in chunk.text.splitlines():
                parsed = self._parse_line(line)
                if parsed:
                    speaker, _ = parsed
                    if speaker != current_speaker:
                        speaker_turns[speaker] = speaker_turns.get(speaker, 0) + 1
                        current_speaker = speaker

        speakers = sorted(
            [{"name": name, "turn_count": count} for name, count in speaker_turns.items()],
            key=lambda x: x["turn_count"],
            reverse=True,
        )
        has_timestamps = self._has_timestamps(
            " ".join(c.text for c in chunks[:10])
        )
        return {
            "speakers": speakers,
            "total_turns": sum(speaker_turns.values()),
            "has_timestamps": has_timestamps,
        }

    def extract_timeline(self, text: str) -> dict:
        """Scan text for date/time stamps and return first/last found."""
        # Patterns: [DD/MM/YYYY, HH:MM], ISO dates YYYY-MM-DD, or HH:MM
        date_pattern = re.compile(
            r"\b(\d{1,2}/\d{1,2}/\d{2,4})"
            r"|(\d{4}-\d{2}-\d{2})"
            r"|(\[\d{1,2}[:/]\d{2})"
        )
        timestamps: list[str] = []
        for m in date_pattern.finditer(text):
            ts = m.group().strip("[]")
            if ts:
                timestamps.append(ts)

        if not timestamps:
            return {"first_timestamp": None, "last_timestamp": None}
        return {"first_timestamp": timestamps[0], "last_timestamp": timestamps[-1]}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _has_timestamps(self, sample: str) -> bool:
        return bool(_PAT_TIMESTAMP.search(sample))

    def _parse_line(self, line: str) -> tuple[str, str] | None:
        """Return (speaker, message) or None if line is not a speaker line."""
        for pat in (_SPEAKER_TIMESTAMP, _SPEAKER_COLON, _SPEAKER_ARROW):
            m = pat.match(line)
            if m:
                return m.group(1).strip(), m.group(2).strip()
        return None

    def _parse_turns(self, text: str) -> list[_Turn]:
        """Group consecutive lines from the same speaker into turns."""
        turns: list[_Turn] = []
        current_turn: _Turn | None = None
        turn_idx = 0

        for line in text.splitlines():
            parsed = self._parse_line(line)
            if parsed:
                speaker, message = parsed
                if current_turn is None or current_turn.speaker != speaker:
                    if current_turn is not None:
                        turns.append(current_turn)
                    current_turn = _Turn(
                        speaker=speaker,
                        text=f"{speaker}: {message}",
                        turn_index=turn_idx,
                        lines=[f"{speaker}: {message}"],
                    )
                    turn_idx += 1
                else:
                    # Same speaker — append to current turn
                    current_turn.lines.append(f"{speaker}: {message}")
                    current_turn.text = "\n".join(current_turn.lines)
            elif current_turn is not None and line.strip():
                # Continuation line (no speaker prefix)
                current_turn.lines.append(line)
                current_turn.text = "\n".join(current_turn.lines)

        if current_turn is not None:
            turns.append(current_turn)

        return turns

    def _build_chunks(self, turns: list[_Turn]) -> list[ConversationChunk]:
        """Pack turns into chunks capped at _MAX_TOKENS with _OVERLAP_TURNS overlap."""
        chunks: list[ConversationChunk] = []
        current_texts: list[str] = []
        current_tokens = 0
        chunk_start_turn_idx = turns[0].turn_index if turns else 0
        first_speaker = turns[0].speaker if turns else ""
        overlap_turns: list[_Turn] = []

        def _flush():
            nonlocal current_texts, current_tokens, chunk_start_turn_idx, first_speaker
            if current_texts:
                chunks.append(
                    ConversationChunk(
                        text="\n".join(current_texts),
                        speaker=first_speaker,
                        turn_index=chunk_start_turn_idx,
                    )
                )
            current_texts = []
            current_tokens = 0

        for i, turn in enumerate(turns):
            turn_tokens = len(turn.text) // 4
            if current_tokens + turn_tokens > _MAX_TOKENS and current_texts:
                _flush()
                # Apply overlap: carry over last _OVERLAP_TURNS turn(s)
                for ot in overlap_turns:
                    current_texts.append(ot.text)
                    current_tokens += len(ot.text) // 4
                chunk_start_turn_idx = (
                    overlap_turns[0].turn_index if overlap_turns else turn.turn_index
                )
                first_speaker = overlap_turns[0].speaker if overlap_turns else turn.speaker

            if not current_texts:
                chunk_start_turn_idx = turn.turn_index
                first_speaker = turn.speaker

            current_texts.append(turn.text)
            current_tokens += turn_tokens
            # Track overlap window
            overlap_turns = turns[max(0, i - _OVERLAP_TURNS + 1) : i + 1]

        _flush()
        return chunks
