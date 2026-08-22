/** Which document, if any, the reader should write into the URL's `doc` param.
 *
 *  `openDoc` must be the store's value *at call time*. The mirror effect runs in
 *  the same commit as the effect that consumes an incoming `?doc=`, so the
 *  `activeDocumentId` its render captured is the document that was open before
 *  the link was followed. Mirroring that value replaced the incoming link, and
 *  the next pass read it back: a Hub "Dive back in" opened whatever the user had
 *  read last instead of the document on the card.
 */
export function docToMirror(urlDoc: string | null, openDoc: string | null): string | null {
  if (!openDoc) return null
  if (urlDoc === openDoc) return null
  return openDoc
}
