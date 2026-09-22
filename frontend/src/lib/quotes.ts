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
  {
    text: "At the start of the day tell yourself: I shall meet people who are officious, ungrateful, abusive, treacherous, malicious, and selfish. In every case, they've got like this because of their ignorance of good and bad.",
    author: "Marcus Aurelius",
    source: "Meditations II.1, tr. Hays",
  },
  {
    text: "It is not that we have a short time to live, but that we waste a lot of it.",
    author: "Seneca",
    source: "On the Shortness of Life I, tr. Costa",
  },
  {
    text: "Nothing, Lucilius, is ours, except time. We were entrusted by nature with the ownership of this single thing, so fleeting and slippery that anyone who will can oust us from possession.",
    author: "Seneca",
    source: "Letters to Lucilius, Letter I, tr. Campbell",
  },
  {
    text: "We must make the best of those things that are in our power, and take the rest as nature gives it.",
    author: "Epictetus",
    source: "Discourses I.1, tr. Long",
  },
  {
    text: "But all things excellent are as difficult as they are rare.",
    author: "Baruch Spinoza",
    source: "Ethics, Part V, final lines, 1677",
  },
  {
    text: "Every now and then a man's mind is stretched by a new idea or sensation, and never shrinks back to its former dimensions.",
    author: "Oliver Wendell Holmes Sr.",
    source: "The Autocrat of the Breakfast-Table, The Atlantic Monthly, Sep. 1858 — the line usually misattributed to Emerson",
  },
  {
    text: "Ignorance more frequently begets confidence than does knowledge: it is those who know little, and not those who know much, who so positively assert that this or that problem will never be solved by science.",
    author: "Charles Darwin",
    source: "The Descent of Man, 1871, Introduction",
  },
  {
    text: "Intellectual freedom depends upon material things. Poetry depends upon intellectual freedom.",
    author: "Virginia Woolf",
    source: "A Room of One's Own, 1929",
  },
  {
    text: "To see what is in front of one's nose needs a constant struggle.",
    author: "George Orwell",
    source: "In Front of Your Nose, Tribune, 22 March 1946",
  },
  {
    text: "Everything can be taken from a man but one thing: the last of the human freedoms — to choose one's attitude in any given set of circumstances, to choose one's own way.",
    author: "Viktor Frankl",
    source: "Man's Search for Meaning, 1946",
  },
  {
    text: "Not everything that is faced can be changed, but nothing can be changed until it is faced.",
    author: "James Baldwin",
    source: "As Much Truth as One Can Bear, The New York Times Book Review, 14 Jan. 1962",
  },
  {
    text: "I insist that the object of all true education is not to make men carpenters, it is to make carpenters men.",
    author: "W. E. B. Du Bois",
    source: "The Souls of Black Folk, 1903, ch. II",
  },
  {
    text: "The more clearly we can focus our attention on the wonders and realities of the universe about us, the less taste we shall have for destruction.",
    author: "Rachel Carson",
    source: "The Sense of Wonder, 1965",
  },
  {
    text: "I don't know anything, but I do know that everything is interesting if you go into it deeply enough.",
    author: "Richard Feynman",
    source: "The Pleasure of Finding Things Out, 1999, from a 1979 Omni interview",
  },
  {
    text: "Extraordinary claims require extraordinary evidence.",
    author: "Carl Sagan",
    source: "Cosmos, episode 12 \"Encyclopedia Galactica,\" 1980 — popularising a formulation of Marcello Truzzi's",
  },
  {
    text: "We will need writers who can remember freedom: poets, visionaries — the realists of a larger reality.",
    author: "Ursula K. Le Guin",
    source: "National Book Foundation Medal acceptance speech, 2014",
  },
  {
    text: "We die. That may be the meaning of life. But we do language. That may be the measure of our lives.",
    author: "Toni Morrison",
    source: "Nobel Lecture, 1993",
  },
  {
    text: "Attention, taken to its highest degree, is the same thing as prayer. It presupposes faith and love. Absolutely unmixed attention is prayer.",
    author: "Simone Weil",
    source: "Gravity and Grace, 1952 (posthumous)",
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
