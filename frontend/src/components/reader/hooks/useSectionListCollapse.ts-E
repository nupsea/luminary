import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import type { SectionItem } from "../types"

interface SectionTree {
  childrenOf: Map<string, string[]>
  descendantCount: Map<string, number>
}

// Owns the collapsed-parents Set + the derived parent->children/descendant tree
// used by the sections list. Defaults: any level<=2 parent that has level>=3
// descendants in a long doc starts collapsed (keeps the dashboard scannable
// for tech books without hiding structure for short articles).
export function useSectionListCollapse(
  sections: SectionItem[] | undefined,
  sectionMap: Map<string, SectionItem>,
  docId: string | undefined,
) {
  const sectionTree = useMemo<SectionTree>(() => {
    const childrenOf = new Map<string, string[]>()
    const descendantCount = new Map<string, number>()
    const list = sections ?? []
    for (const s of list) {
      if (!s.parent_section_id) continue
      const arr = childrenOf.get(s.parent_section_id) ?? []
      arr.push(s.id)
      childrenOf.set(s.parent_section_id, arr)
    }
    for (const s of list) {
      let pid = s.parent_section_id
      while (pid) {
        descendantCount.set(pid, (descendantCount.get(pid) ?? 0) + 1)
        pid = sectionMap.get(pid)?.parent_section_id ?? null
      }
    }
    return { childrenOf, descendantCount }
  }, [sections, sectionMap])

  const [collapsedParents, setCollapsedParents] = useState<Set<string>>(new Set())
  const initialCollapsedRef = useRef<string | null>(null)

  useEffect(() => {
    if (!sections || initialCollapsedRef.current === docId) return
    initialCollapsedRef.current = docId ?? null
    if (sections.length <= 30) {
      setCollapsedParents(new Set())
      return
    }
    const next = new Set<string>()
    for (const s of sections) {
      if (s.level > 2) continue
      const kids = sectionTree.childrenOf.get(s.id) ?? []
      const hasDeep = kids.some((cid) => (sectionMap.get(cid)?.level ?? 0) >= 3)
      if (hasDeep) next.add(s.id)
    }
    setCollapsedParents(next)
  }, [sections, docId, sectionTree, sectionMap])

  const toggleCollapsed = useCallback((sid: string) => {
    setCollapsedParents((prev) => {
      const next = new Set(prev)
      if (next.has(sid)) next.delete(sid)
      else next.add(sid)
      return next
    })
  }, [])

  const isSectionHidden = useCallback(
    (sec: SectionItem): boolean => {
      let pid = sec.parent_section_id
      while (pid) {
        if (collapsedParents.has(pid)) return true
        pid = sectionMap.get(pid)?.parent_section_id ?? null
      }
      return false
    },
    [collapsedParents, sectionMap],
  )

  return {
    sectionTree,
    collapsedParents,
    setCollapsedParents,
    toggleCollapsed,
    isSectionHidden,
  }
}
