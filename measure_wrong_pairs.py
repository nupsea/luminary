"""Cosine of wrong-option pairs judged by reading: repeats, and distinct claims."""

REPEATS = [
    ("The landlord offered to let me use his own bed temporarily.", "The landlord offered to sleep on his own bed instead."),
    ("The scalability issues are primarily due to the low number of followers each user has rather than the many they follow.",
     "Each user following and being followed by a small number of people causes Twitter's scaling difficulties, not many connections."),
]
DISTINCT = [
    ("The guest demands to know about the harpooneer's past adventures at sea and his reputation among sailors.",
     "The guest wants to know if the harpooneer is a notorious criminal and if he will be safe with him."),
    ("The guest wants to know if the harpooneer is a notorious criminal and if he will be safe with him.",
     "The guest wants to know if the harpooneer has any connections to the landlord's family and if it's safe to stay under one roof."),
    ("Monitoring the cause of problems when systems are operating smoothly.", "Avoiding problematic changes by monitoring external network conditions."),
    ("It increases queues artificially, making measurements accurate.", "It keeps queues longer artificially, improving real-world accuracy."),
    ("It keeps queues artificially long, skewing measurements of real-world performance.", "It keeps queues artificially short, but does not affect the overall system performance."),
    ("The term 'NoSQL' was created to describe closed-source, non-relational database systems.", "The hashtag was first used to label discussions about relational database limitations."),
    ("The landlord offered to let me use his own bed temporarily.", "The landlord suggested staying in a tent outside for the night."),
]
if __name__ == "__main__":
  from app.services.quiz_builder import _cosines
  for label, pairs in (("repeat", REPEATS), ("distinct", DISTINCT)):
    for a, b in pairs:
        print(label, f"{_cosines([a, b])[0, 1]:.3f}", a[:50], "|", b[:50])
