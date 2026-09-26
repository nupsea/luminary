; Tauri's uninstaller deletes the whole library, $LOCALAPPDATA\${BUNDLEID}, when its
; checkbox is ticked. The box's label is ours (English.nsh); this asks once more,
; defaulting to No, and says where the library is when it is kept.

!define MUI_UNCONFIRMPAGE_TEXT_TOP "Luminary will be removed from the folder below. Your library is kept unless you tick the box to delete it."

!macro NSIS_HOOK_PREUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    ${IfNot} ${Cmd} `MessageBox MB_YESNO|MB_ICONEXCLAMATION|MB_DEFBUTTON2 "Permanently delete your Luminary library?$\r$\n$\r$\n$LOCALAPPDATA\${BUNDLEID}$\r$\n$\r$\nIt holds every document, note, flashcard and review you created, your settings (including API keys) and the downloaded models. This cannot be undone.$\r$\n$\r$\nChoose No to remove only the app and keep your library." /SD IDNO IDYES`
      StrCpy $DeleteAppDataCheckboxState 0
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $UpdateMode <> 1
  ${AndIf} $PassiveMode <> 1
  ${AndIfNot} ${Silent}
  ${AndIf} ${FileExists} "$LOCALAPPDATA\${BUNDLEID}\*.*"
    MessageBox MB_OK|MB_ICONINFORMATION "Luminary is removed. Your library was kept at:$\r$\n$\r$\n$LOCALAPPDATA\${BUNDLEID}$\r$\n$\r$\nReinstalling Luminary picks it up again. To delete it, delete that folder."
  ${EndIf}
!macroend
