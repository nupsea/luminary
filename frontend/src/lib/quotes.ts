// Quotes on learning, character and ethics, one a day.
//
// Every entry carries a checkable source. Most circulating quote lists are
// wrong about who said what -- "we are what we repeatedly do" is Will Durant
// summarising Aristotle, and "education is not the filling of a pail" is
// Plutarch rather than Yeats -- and a wrong attribution in a learning tool is
// worse than no quote. Anything that could not be traced to a work was dropped
// rather than printed with a hedge.

export interface Quote {
  text: string
  author: string
  /** Where to check it. */
  source: string
}

export const QUOTES: readonly Quote[] = [
  {
    text: "When you know a thing, to hold that you know it; and when you do not know a thing, to allow that you do not know it — this is knowledge.",
    author: "Confucius",
    source: "Analects II.17, tr. Legge",
  },
  {
    text: "He who learns but does not think is lost. He who thinks but does not learn is in great danger.",
    author: "Confucius",
    source: "Analects II.15",
  },
  {
    text: "The first principle is that you must not fool yourself — and you are the easiest person to fool.",
    author: "Richard Feynman",
    source: "Cargo Cult Science, Caltech commencement, 1974",
  },
  {
    text: "We are what we repeatedly do. Excellence, then, is not an act, but a habit.",
    author: "Will Durant",
    source: "The Story of Philosophy, 1926 — summarising Aristotle",
  },
  {
    text: "We become just by doing just acts, temperate by doing temperate acts, brave by doing brave acts.",
    author: "Aristotle",
    source: "Nicomachean Ethics II.1",
  },
  {
    text: "Learned we may be with another man's learning: we can only be wise with wisdom of our own.",
    author: "Michel de Montaigne",
    source: "Essays I.25, tr. Screech",
  },
  {
    text: "It is impossible for a man to learn what he thinks he already knows.",
    author: "Epictetus",
    source: "Discourses II.17",
  },
  {
    text: "Men are disturbed not by things, but by the views which they take of things.",
    author: "Epictetus",
    source: "Enchiridion V",
  },
  {
    text: "The unexamined life is not worth living.",
    author: "Socrates",
    source: "Plato, Apology 38a",
  },
  {
    text: "Much learning does not teach understanding.",
    author: "Heraclitus",
    source: "Fragment DK B40",
  },
  {
    text: "The mind is not a vessel to be filled but a fire to be kindled.",
    author: "Plutarch",
    source: "On Listening to Lectures, 48c",
  },
  {
    text: "Men learn while they teach.",
    author: "Seneca",
    source: "Letters to Lucilius 7.8",
  },
  {
    text: "Read not to contradict and confute, nor to believe and take for granted, but to weigh and consider.",
    author: "Francis Bacon",
    source: "Of Studies, 1625",
  },
  {
    text: "It is not enough to have a good mind; the main thing is to use it well.",
    author: "René Descartes",
    source: "Discourse on the Method, 1637",
  },
  {
    text: "I have laboured carefully not to mock, lament, or execrate human actions, but to understand them.",
    author: "Baruch Spinoza",
    source: "Tractatus Politicus I.4",
  },
  {
    text: "Doubt is not a pleasant condition, but certainty is absurd.",
    author: "Voltaire",
    source: "Letter to Frederick II of Prussia, 1767",
  },
  {
    text: "Act only according to that maxim whereby you can at the same time will that it should become a universal law.",
    author: "Immanuel Kant",
    source: "Groundwork of the Metaphysics of Morals, 1785",
  },
  {
    text: "He who knows only his own side of the case knows little of that.",
    author: "John Stuart Mill",
    source: "On Liberty, 1859, ch. 2",
  },
  {
    text: "Your ability to control your thoughts — treat it with respect. It's all that protects your mind from false perceptions.",
    author: "Marcus Aurelius",
    source: "Meditations III.9, tr. Hays",
  },
  {
    text: "To feel affection for people even when they make mistakes is uniquely human. You can do it, if you simply recognize that they're human too.",
    author: "Marcus Aurelius",
    source: "Meditations VII.22, tr. Hays",
  },
  {
    text: "Waste no more time arguing about what a good man should be. Be one.",
    author: "Marcus Aurelius",
    source: "Meditations X.16, tr. Hays",
  },
  {
    text: "Nothing in life is to be feared, it is only to be understood. Now is the time to understand more, so that we may fear less.",
    author: "Marie Curie",
    source: "Quoted in Eve Curie, Madame Curie, 1937",
  },
  {
    text: "The whole problem with the world is that fools and fanatics are always so certain of themselves, and wiser people so full of doubts.",
    author: "Bertrand Russell",
    source: "The Triumph of Stupidity, 1933",
  },
  {
    text: "Attention is the rarest and purest form of generosity.",
    author: "Simone Weil",
    source: "Letter to Joë Bousquet, 1942",
  },
  {
    text: "Love is the extremely difficult realisation that something other than oneself is real.",
    author: "Iris Murdoch",
    source: "The Sublime and the Good, 1959",
  },
  {
    text: "The sad truth is that most evil is done by people who never make up their minds to be good or evil.",
    author: "Hannah Arendt",
    source: "The Life of the Mind, 1978",
  },
]

/** Day of the year in UTC, so the quote turns over at the same moment for everyone. */
function dayOfYear(now: Date): number {
  const startOfYear = Date.UTC(now.getUTCFullYear(), 0, 0)
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  return Math.floor((today - startOfYear) / 86_400_000)
}

/**
 * The same quote all day, a different one tomorrow.
 *
 * `offset` shifts the sequence so two surfaces showing a quote on the same day
 * do not show the same one. Deterministic rather than random: a quote that
 * changed on every render would be noise, and one that changed on every relaunch
 * could never be finished reading.
 */
export function quoteOfTheDay(now: Date = new Date(), offset = 0): Quote {
  const index = (((dayOfYear(now) + offset) % QUOTES.length) + QUOTES.length) % QUOTES.length
  return QUOTES[index]
}
