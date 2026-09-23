import { describe, expect, it, vi } from "vitest"
import { handleEpubKeyboardShortcut } from "./EPUBViewer"

describe("handleEpubKeyboardShortcut", () => {
  it("navigates to the next chapter on ArrowRight", () => {
    const onNextChapter = vi.fn()
    const onPrevChapter = vi.fn()
    const onCloseLightbox = vi.fn()
    const preventDefault = vi.fn()

    const handled = handleEpubKeyboardShortcut(
      { key: "ArrowRight", preventDefault },
      {
        activeChapter: 2,
        totalChapters: 10,
        zoomedImgSrc: null,
        onNextChapter,
        onPrevChapter,
        onCloseLightbox,
      },
    )

    expect(handled).toBe(true)
    expect(preventDefault).toHaveBeenCalled()
    expect(onNextChapter).toHaveBeenCalledTimes(1)
    expect(onPrevChapter).not.toHaveBeenCalled()
  })

  it("navigates to the previous chapter on ArrowLeft", () => {
    const onNextChapter = vi.fn()
    const onPrevChapter = vi.fn()
    const onCloseLightbox = vi.fn()
    const preventDefault = vi.fn()

    const handled = handleEpubKeyboardShortcut(
      { key: "ArrowLeft", preventDefault },
      {
        activeChapter: 2,
        totalChapters: 10,
        zoomedImgSrc: null,
        onNextChapter,
        onPrevChapter,
        onCloseLightbox,
      },
    )

    expect(handled).toBe(true)
    expect(preventDefault).toHaveBeenCalled()
    expect(onPrevChapter).toHaveBeenCalledTimes(1)
    expect(onNextChapter).not.toHaveBeenCalled()
  })

  it("supports PageDown and PageUp keys", () => {
    const onNextChapter = vi.fn()
    const onPrevChapter = vi.fn()
    const onCloseLightbox = vi.fn()

    expect(
      handleEpubKeyboardShortcut(
        { key: "PageDown" },
        {
          activeChapter: 1,
          totalChapters: 5,
          zoomedImgSrc: null,
          onNextChapter,
          onPrevChapter,
          onCloseLightbox,
        },
      ),
    ).toBe(true)
    expect(onNextChapter).toHaveBeenCalledTimes(1)

    expect(
      handleEpubKeyboardShortcut(
        { key: "PageUp" },
        {
          activeChapter: 2,
          totalChapters: 5,
          zoomedImgSrc: null,
          onNextChapter,
          onPrevChapter,
          onCloseLightbox,
        },
      ),
    ).toBe(true)
    expect(onPrevChapter).toHaveBeenCalledTimes(1)
  })

  it("clamps at chapter boundaries", () => {
    const onNextChapter = vi.fn()
    const onPrevChapter = vi.fn()
    const onCloseLightbox = vi.fn()

    // At first chapter, cannot go prev
    const atFirst = handleEpubKeyboardShortcut(
      { key: "ArrowLeft" },
      {
        activeChapter: 0,
        totalChapters: 5,
        zoomedImgSrc: null,
        onNextChapter,
        onPrevChapter,
        onCloseLightbox,
      },
    )
    expect(atFirst).toBe(false)
    expect(onPrevChapter).not.toHaveBeenCalled()

    // At last chapter, cannot go next
    const atLast = handleEpubKeyboardShortcut(
      { key: "ArrowRight" },
      {
        activeChapter: 4,
        totalChapters: 5,
        zoomedImgSrc: null,
        onNextChapter,
        onPrevChapter,
        onCloseLightbox,
      },
    )
    expect(atLast).toBe(false)
    expect(onNextChapter).not.toHaveBeenCalled()
  })

  it("closes diagram lightbox on Escape", () => {
    const onNextChapter = vi.fn()
    const onPrevChapter = vi.fn()
    const onCloseLightbox = vi.fn()
    const preventDefault = vi.fn()

    const handled = handleEpubKeyboardShortcut(
      { key: "Escape", preventDefault },
      {
        activeChapter: 2,
        totalChapters: 10,
        zoomedImgSrc: "/images/diagram.png",
        onNextChapter,
        onPrevChapter,
        onCloseLightbox,
      },
    )

    expect(handled).toBe(true)
    expect(preventDefault).toHaveBeenCalled()
    expect(onCloseLightbox).toHaveBeenCalledTimes(1)
  })

  it("ignores Escape when lightbox is not open", () => {
    const onCloseLightbox = vi.fn()
    const handled = handleEpubKeyboardShortcut(
      { key: "Escape" },
      {
        activeChapter: 2,
        totalChapters: 10,
        zoomedImgSrc: null,
        onNextChapter: vi.fn(),
        onPrevChapter: vi.fn(),
        onCloseLightbox,
      },
    )
    expect(handled).toBe(false)
    expect(onCloseLightbox).not.toHaveBeenCalled()
  })

  it("ignores unrelated keys", () => {
    const onNextChapter = vi.fn()
    const onPrevChapter = vi.fn()
    const handled = handleEpubKeyboardShortcut(
      { key: " " },
      {
        activeChapter: 2,
        totalChapters: 10,
        zoomedImgSrc: null,
        onNextChapter,
        onPrevChapter,
        onCloseLightbox: vi.fn(),
      },
    )
    expect(handled).toBe(false)
    expect(onNextChapter).not.toHaveBeenCalled()
    expect(onPrevChapter).not.toHaveBeenCalled()
  })
})
