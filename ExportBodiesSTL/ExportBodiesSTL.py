"""
Export Bodies  -  Fusion add-in  (v1.1)
Adds a button (Solid > Utilities > Add-Ins panel, pinned to the toolbar).
Lists every solid body in the design; tick the ones you want and export each
as its own STL / 3MF / OBJ file.

Features
  - Format: STL, 3MF or OBJ, with mesh quality
  - Remembers last folder and all settings (settings.json next to this file)
  - Placement: assembly position, component origin, or bounding-box corner at 0,0,0
  - Scale factor (STL / OBJ)
  - Filename prefix / suffix, optional document-name prefix
"""
import adsk.core
import adsk.fusion
import json
import os
import re
import struct
import traceback

CMD_ID = 'cc_exportBodiesSTL'
CMD_NAME = 'Export Bodies (STL / 3MF / OBJ)'
CMD_TOOLTIP = 'Choose bodies and export each one as a separate mesh file'
PANEL_ID = 'SolidScriptsAddinsPanel'

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
DEFAULTS = {
    'folder': '', 'format': 'STL', 'quality': 'Medium',
    'placement': 'Assembly position', 'scale': '1',
    'prefix': '', 'suffix': '', 'useDocName': False,
}
FORMATS = ['STL', '3MF', 'OBJ']
QUALITIES = ['High', 'Medium', 'Low']
PLACEMENTS = ['Assembly position', 'Component origin', 'Move to origin (bbox corner)']

_app = None
_ui = None
_handlers = []   # keep references alive, otherwise Python garbage-collects them
_bodies = []     # [(label, BRepBody)] captured when the dialog opens
_folder = ''     # currently chosen output folder


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, 'r') as f:
            s.update(json.load(f))
    except Exception:
        pass
    return s


def save_settings(s):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass   # settings are a convenience, never fatal


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def collect_bodies(design):
    """Return [(label, body)] for all solid bodies, in assembly context."""
    root = design.rootComponent
    found = []
    for body in root.bRepBodies:
        if body.isSolid:
            found.append((body.name, body))
    for occ in root.allOccurrences:
        for body in occ.bRepBodies:      # proxies, positioned in the assembly
            if body.isSolid:
                found.append((f'{occ.name} / {body.name}', body))
    return found


def safe_filename(text):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', text).strip(' .')
    return text or 'body'


def fill_dropdown(dropdown, names, selected):
    if selected not in names:
        selected = names[0] if selected is None else names[0]
    for n in names:
        dropdown.listItems.add(n, n == selected)


def parse_scale(text):
    try:
        v = float(str(text).replace(',', '.'))
        return v if v > 0 else None
    except Exception:
        return None


def doc_name():
    name = _app.activeDocument.name
    return re.sub(r'\s+v\d+$', '', name)


# ---- mesh post-processing (scale / move bbox corner to origin) ------------
def process_stl(path, scale, to_origin):
    with open(path, 'rb') as f:
        data = f.read()
    count = struct.unpack_from('<I', data, 80)[0]
    if count == 0:
        return
    if len(data) != 84 + 50 * count:
        raise ValueError('not a binary STL')
    tris = list(struct.iter_unpack('<12fH', data[84:]))
    shift = [0.0, 0.0, 0.0]
    if to_origin:
        mins = [float('inf')] * 3
        for t in tris:
            for v in (3, 6, 9):
                for a in range(3):
                    if t[v + a] < mins[a]:
                        mins[a] = t[v + a]
        shift = [-m * scale for m in mins]
    out = bytearray(data[:80])
    out += struct.pack('<I', count)
    for t in tris:
        out += struct.pack(
            '<12fH',
            t[0], t[1], t[2],
            t[3] * scale + shift[0], t[4] * scale + shift[1], t[5] * scale + shift[2],
            t[6] * scale + shift[0], t[7] * scale + shift[1], t[8] * scale + shift[2],
            t[9] * scale + shift[0], t[10] * scale + shift[1], t[11] * scale + shift[2],
            t[12])
    with open(path, 'wb') as f:
        f.write(out)


def process_obj(path, scale, to_origin):
    with open(path, 'r') as f:
        lines = f.readlines()
    mins = [float('inf')] * 3
    for ln in lines:
        if ln.startswith('v '):
            p = ln.split()
            for a in range(3):
                mins[a] = min(mins[a], float(p[1 + a]))
    if mins[0] == float('inf'):
        return
    shift = [-m * scale for m in mins] if to_origin else [0.0, 0.0, 0.0]
    out = []
    for ln in lines:
        if ln.startswith('v '):
            p = ln.split()
            xyz = [float(p[1 + a]) * scale + shift[a] for a in range(3)]
            extra = (' ' + ' '.join(p[4:])) if len(p) > 4 else ''
            out.append('v %.6f %.6f %.6f%s\n' % (xyz[0], xyz[1], xyz[2], extra))
        else:
            out.append(ln)
    with open(path, 'w') as f:
        f.writelines(out)


# --------------------------------------------------------------------------
# Event handlers
# --------------------------------------------------------------------------
class CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        global _bodies, _folder
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _ui.messageBox('Open a Design (Model workspace) first.')
                return
            _bodies = collect_bodies(design)
            if not _bodies:
                _ui.messageBox('No solid bodies found in this design.')
                return

            s = load_settings()
            _folder = s['folder'] if s['folder'] and os.path.isdir(s['folder']) else ''

            cmd = args.command
            cmd.okButtonText = 'Export'
            cmd.setDialogInitialSize(400, 640)
            inputs = cmd.commandInputs

            # --- bodies ---
            inputs.addBoolValueInput('selectAll', 'Select all', True, '', True)
            g = inputs.addGroupCommandInput('bodyGroup', f'Bodies ({len(_bodies)})')
            g.isExpanded = True
            for i, (label, body) in enumerate(_bodies):
                g.children.addBoolValueInput(f'body_{i}', label, True, '', body.isVisible)

            # --- output ---
            g = inputs.addGroupCommandInput('outGroup', 'Output')
            g.isExpanded = True
            c = g.children
            fmt = c.addDropDownCommandInput(
                'format', 'Format', adsk.core.DropDownStyles.TextListDropDownStyle)
            fill_dropdown(fmt, FORMATS, s['format'])
            q = c.addDropDownCommandInput(
                'quality', 'Mesh quality', adsk.core.DropDownStyles.TextListDropDownStyle)
            fill_dropdown(q, QUALITIES, s['quality'])
            c.addTextBoxCommandInput('folderText', 'Folder', _folder or '(not set)', 2, True)
            c.addBoolValueInput('chooseFolder', 'Choose folder...', False, '', False)

            # --- options ---
            g = inputs.addGroupCommandInput('optGroup', 'Options')
            g.isExpanded = True
            c = g.children
            pl = c.addDropDownCommandInput(
                'placement', 'Placement', adsk.core.DropDownStyles.TextListDropDownStyle)
            fill_dropdown(pl, PLACEMENTS, s['placement'])
            sc = c.addStringValueInput('scale', 'Scale factor', str(s['scale']))
            sc.tooltip = ('Multiplies all coordinates (STL / OBJ only). '
                          'Use 10 or 0.1 to convert between cm and mm, 25.4 for inches.')
            sc.isVisible = (fmt.selectedItem.name != '3MF')
            c.addBoolValueInput('useDocName', 'Prefix with document name', True, '',
                                bool(s['useDocName']))
            c.addStringValueInput('prefix', 'Filename prefix', s['prefix'])
            c.addStringValueInput('suffix', 'Filename suffix', s['suffix'])

            h = InputChangedHandler(); cmd.inputChanged.add(h); _handlers.append(h)
            h = ValidateHandler();     cmd.validateInputs.add(h); _handlers.append(h)
            h = ExecuteHandler();      cmd.execute.add(h); _handlers.append(h)
        except:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        global _folder
        try:
            iid = args.input.id
            if iid == 'selectAll':
                state = args.input.value
                for i in range(len(_bodies)):
                    args.inputs.itemById(f'body_{i}').value = state
            elif iid == 'chooseFolder':
                dlg = _ui.createFolderDialog()
                dlg.title = 'Choose a folder for the exported files'
                if _folder and os.path.isdir(_folder):
                    dlg.initialDirectory = _folder
                if dlg.showDialog() == adsk.core.DialogResults.DialogOK:
                    _folder = dlg.folder
                    args.inputs.itemById('folderText').formattedText = _folder
                args.input.value = False
            elif iid == 'format':
                name = adsk.core.DropDownCommandInput.cast(args.input).selectedItem.name
                args.inputs.itemById('scale').isVisible = (name != '3MF')
        except:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


class ValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inp = args.inputs
            any_body = any(inp.itemById(f'body_{i}').value for i in range(len(_bodies)))
            ok_scale = parse_scale(inp.itemById('scale').value) is not None
            args.areInputsValid = bool(any_body and _folder and ok_scale)
        except:
            args.areInputsValid = False


class ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            design = adsk.fusion.Design.cast(_app.activeProduct)
            inp = args.command.commandInputs

            chosen = [_bodies[i] for i in range(len(_bodies))
                      if inp.itemById(f'body_{i}').value]
            if not chosen or not _folder:
                return

            fmt = inp.itemById('format').selectedItem.name
            quality = inp.itemById('quality').selectedItem.name
            placement = inp.itemById('placement').selectedItem.name
            scale = parse_scale(inp.itemById('scale').value) or 1.0
            prefix = inp.itemById('prefix').value.strip()
            suffix = inp.itemById('suffix').value.strip()
            use_doc = inp.itemById('useDocName').value

            save_settings({
                'folder': _folder, 'format': fmt, 'quality': quality,
                'placement': placement, 'scale': inp.itemById('scale').value,
                'prefix': prefix, 'suffix': suffix, 'useDocName': use_doc,
            })

            refinement = {
                'High': adsk.fusion.MeshRefinementSettings.MeshRefinementHigh,
                'Medium': adsk.fusion.MeshRefinementSettings.MeshRefinementMedium,
                'Low': adsk.fusion.MeshRefinementSettings.MeshRefinementLow,
            }[quality]
            ext = '.' + fmt.lower()
            to_origin = placement.startswith('Move to origin')
            do_post = fmt in ('STL', 'OBJ') and (scale != 1.0 or to_origin)

            export_mgr = design.exportManager
            docname = doc_name() if use_doc else ''
            used = {}
            ok, failed = 0, []
            for label, body in chosen:
                parts = []
                if docname:
                    parts.append(docname)
                if prefix:
                    parts.append(prefix)
                parts.append(label.replace(' / ', '_'))
                if suffix:
                    parts.append(suffix)
                name = safe_filename('_'.join(parts))
                n = used.get(name.lower(), 0)
                used[name.lower()] = n + 1
                if n:
                    name = f'{name}_{n + 1}'
                path = os.path.join(_folder, name + ext)

                geom = body
                if placement == 'Component origin':
                    native = body.nativeObject      # None for root-level bodies
                    if native:
                        geom = native
                try:
                    if fmt == 'STL':
                        opts = export_mgr.createSTLExportOptions(geom, path)
                        opts.isBinaryFormat = True
                    elif fmt == '3MF':
                        opts = export_mgr.create3MFExportOptions(geom, path)
                    else:
                        opts = export_mgr.createOBJExportOptions(geom, path)
                    try:
                        opts.meshRefinement = refinement
                    except Exception:
                        pass
                    if not export_mgr.execute(opts):
                        failed.append(label)
                        continue
                    if do_post:
                        if fmt == 'STL':
                            process_stl(path, scale, to_origin)
                        else:
                            process_obj(path, scale, to_origin)
                    ok += 1
                except:
                    failed.append(label)

            msg = f'Exported {ok} of {len(chosen)} bodies ({fmt}) to:\n{_folder}'
            if fmt == '3MF' and (scale != 1.0 or to_origin):
                msg += '\n\nNote: scale factor and "move to origin" are not applied to 3MF.'
            if failed:
                msg += '\n\nFailed:\n' + '\n'.join(failed)
            _ui.messageBox(msg)
        except:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


# --------------------------------------------------------------------------
# Add-in entry points
# --------------------------------------------------------------------------
def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        cmd_def = _ui.commandDefinitions.addButtonDefinition(CMD_ID, CMD_NAME, CMD_TOOLTIP)

        h = CommandCreatedHandler()
        cmd_def.commandCreated.add(h)
        _handlers.append(h)

        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        if not panel.controls.itemById(CMD_ID):
            control = panel.controls.addCommand(cmd_def)
            control.isPromoted = True
    except:
        if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))


def stop(context):
    try:
        panel = _ui.allToolbarPanels.itemById(PANEL_ID)
        control = panel.controls.itemById(CMD_ID)
        if control:
            control.deleteMe()
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except:
        if _ui:
            _ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
