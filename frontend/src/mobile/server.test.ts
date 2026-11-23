import { describe, expect, it } from "vitest"

import { parseServer } from "./server"

describe("parseServer", () => {
  it("takes an https address, with or without the scheme, and puts the API under /api", () => {
    expect(parseServer("luminary.tail1234.ts.net")).toEqual({
      origin: "https://luminary.tail1234.ts.net",
      apiBase: "https://luminary.tail1234.ts.net/api",
    })
    expect(parseServer(" https://host.example/anything ")).toEqual({
      origin: "https://host.example",
      apiBase: "https://host.example/api",
    })
  })

  it("refuses plain http beyond loopback, which a phone would send in the clear", () => {
    expect(parseServer("http://192.168.1.20:7820")).toHaveProperty("error")
    expect(parseServer("http://localhost:7820")).toEqual({
      origin: "http://localhost:7820",
      apiBase: "http://localhost:7820/api",
    })
  })

  it("names an address it cannot read", () => {
    expect(parseServer("https://")).toEqual({ error: "That is not an address." })
  })
})
