import { describe, expect, it } from "vitest"

import { ApiError } from "./apiClient"
import {
  type Connector,
  type ConnectorPreview,
  connectorForUrl,
  fieldValues,
  defaultPicks,
  offeredFromCatalogue,
  pickInput,
  signInRequiredFor,
  togglePick,
} from "./connectorsApi"

function connector(name: string, url_prefixes: string[], extra: Partial<Connector> = {}): Connector {
  return {
    name,
    label: name,
    version: "0.1.0",
    licence: "Apache-2.0",
    terms: { statement: "s", url: "https://example.com/terms" },
    url_prefixes,
    inputs: [],
    credentials: [],
    preview: false,
    connected: true,
    ...extra,
  }
}

const youtube = connector("youtube", ["https://www.youtube.com/watch", "https://youtu.be/"])
const books = connector("books", ["https://books.example/"])

describe("connectorForUrl", () => {
  it("routes a link to the connector whose prefix it starts with", () => {
    expect(connectorForUrl([books, youtube], "https://youtu.be/abc")?.name).toBe("youtube")
    expect(connectorForUrl([books, youtube], "  https://books.example/library/view/x/1/ ")?.name).toBe(
      "books",
    )
  })

  it("never claims a link that only mentions a prefix", () => {
    expect(connectorForUrl([youtube], "https://example.com/?u=https://youtu.be/abc")).toBeNull()
    expect(connectorForUrl([youtube], "")).toBeNull()
  })

  it("takes the first by name when two claim a link, as the backend does", () => {
    const b = connector("b-source", ["https://x.example/"])
    const a = connector("a-source", ["https://x.example/"])
    expect(connectorForUrl([b, a], "https://x.example/page")?.name).toBe("a-source")
  })
})

describe("signInRequiredFor", () => {
  it("names the connector a 401 asks for", () => {
    const err = new ApiError(401, "Unauthorized", JSON.stringify({ detail: "Connect Books first.", connector: "books" }))
    expect(signInRequiredFor(err)).toBe("books")
  })

  it("is null for any other failure", () => {
    expect(signInRequiredFor(new ApiError(401, "Unauthorized", JSON.stringify({ detail: "x" })))).toBeNull()
    expect(signInRequiredFor(new ApiError(503, "x", JSON.stringify({ connector: "books" })))).toBeNull()
    expect(signInRequiredFor(new Error("network"))).toBeNull()
  })
})

const preview: ConnectorPreview = {
  title: "Fixture Systems",
  detail: "",
  choices: [
    {
      field: "chapters",
      label: "Chapters",
      multiple: true,
      default: ["0", "2"],
      options: [
        { value: "0", label: "Preface", detail: "" },
        { value: "1", label: "Storage", detail: "" },
        { value: "2", label: "Replication", detail: "" },
      ],
    },
    {
      field: "captions",
      label: "Transcript",
      multiple: false,
      default: ["en"],
      options: [
        { value: "en", label: "Captions: en", detail: "" },
        { value: "transcribe", label: "Transcribe the audio", detail: "" },
      ],
    },
  ],
}

describe("preview picks", () => {
  it("start at the connector's defaults and become its fetch input", () => {
    const picks = defaultPicks(preview)
    expect(pickInput(preview, picks)).toEqual({
      input: { chapters: ["0", "2"], captions: "en" },
      missing: [],
    })
  })

  it("toggle a multiple choice in the connector's order, and replace a single one", () => {
    const [chapters, captions] = preview.choices
    let picks = togglePick(defaultPicks(preview), chapters, "1")
    expect(picks.chapters).toEqual(["0", "1", "2"])
    picks = togglePick(picks, chapters, "0")
    expect(picks.chapters).toEqual(["1", "2"])
    picks = togglePick(picks, captions, "transcribe")
    expect(picks.captions).toEqual(["transcribe"])
  })

  it("name a choice left empty instead of sending it", () => {
    const picks = { ...defaultPicks(preview), chapters: [] }
    expect(pickInput(preview, picks)).toEqual({ input: { captions: "en" }, missing: ["Chapters"] })
  })
})

describe("fieldValues", () => {
  const fields = [
    { name: "cookies", label: "Session cookies", secret: true, required: true, help: "", multiline: true },
    { name: "note", label: "Note", secret: false, required: false, help: "", multiline: false },
  ]

  it("sends what was typed, trimmed, and names a required field left blank", () => {
    expect(fieldValues(fields, { cookies: "  a=b  ", note: "" })).toEqual({ values: { cookies: "a=b" }, missing: [] })
    expect(fieldValues(fields, { cookies: "   " })).toEqual({ values: {}, missing: ["Session cookies"] })
  })
})

describe("offeredFromCatalogue", () => {
  const item = (name: string, version: string, installed_version: string | null) => ({
    name,
    label: name,
    version,
    summary: "",
    licence: "Apache-2.0",
    terms: { statement: "s", url: "https://example.com/terms" },
    repository: "https://example.com/repo",
    size_bytes: 1,
    installed_version,
  })

  it("offers what is not installed and what the catalogue has newer, never what is current", () => {
    const offered = offeredFromCatalogue([item("a", "0.2.0", null), item("b", "0.2.0", "0.1.0"), item("c", "0.2.0", "0.2.0")])
    expect(offered.map((i) => i.name)).toEqual(["a", "b"])
  })
})
