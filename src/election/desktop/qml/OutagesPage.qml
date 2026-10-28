pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var outages
    required property var words
    property string locale: "tc"
    readonly property var editorState: outages.state
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var paperForm: editorState.paper_forms || ({})
    readonly property var existingReceipt: editorState.existing_receipt || ({})
    readonly property var matchingPaper: (selected.paper_records || []).find(function(paper) {
        return paper.id === page.editorState.selected_paper_id
    }) || ({})
    readonly property bool matchingDraft: !!(existingReceipt.request_id || existingReceipt.reason
        || (existingReceipt.checked || {}).status)
    readonly property bool matchingAllowed: active && matchingPaper.status === "pending"
        && ((matchingPaper.workflow === "count" && editorState.role === "counting_officer")
            || ((matchingPaper.workflow === "allocation" || matchingPaper.workflow === "turnout")
                && editorState.role === "polling_officer"))
    readonly property var checkedPaper: ({workflow: matchingPaper.workflow,
        reentry: {record: (existingReceipt.checked || {}).record || ({})}})
    readonly property bool working: !!editorState.busy || !!editorState.refreshing
    readonly property bool active: !!editorState.writable
    readonly property bool operational: editorState.role === "polling_officer"
        || editorState.role === "counting_officer"
    readonly property bool outageEditable: page.active && page.operational && !page.working
        && !editorState.uncertain_save && !page.matchingDraft
    readonly property bool paperEditable: !!editorState.paper_editable && !page.working
        && !editorState.uncertain_save && !page.matchingDraft
    property int pendingOutageId: 0
    property bool pendingNewOutage: false
    property string pendingWorkflow: ""
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    property var kindOptions: []
    property var workflowOptions: []
    property var actionOptions: []
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function exportReport(format) {
        if (!selected.id || working || editorState.dirty || editorState.newer_revision
                || editorState.uncertain_save) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/outage-"
            + selected.id + "-revision-" + selected.revision + "-" + locale + "." + format
        exportDialog.open()
    }
    function exact(value) { return value === undefined || value === null ? "—" : String(value) }
    function quantity(row, key) {
        var display = row[key + "_display"]
        return display === undefined ? page.exact(row[key]) : String(display)
    }
    function timeHkt(value) {
        if (!value) return "—"
        var match = /^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$/.exec(value)
        if (!match) return String(value)
        var zoneMinutes = 0
        if (match[8] !== "Z") {
            var zone = match[8]
            zoneMinutes = (Number(zone.slice(1, 3)) * 60 + Number(zone.slice(4, 6)))
                * (zone[0] === "+" ? 1 : -1)
        }
        var utc = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]),
            Number(match[4]), Number(match[5]), Number(match[6])) - zoneMinutes * 60000
        var local = new Date(utc + 8 * 60 * 60000)
        function pad(number) { return String(number).padStart(2, "0") }
        return local.getUTCFullYear() + "-" + pad(local.getUTCMonth() + 1) + "-"
            + pad(local.getUTCDate()) + " " + pad(local.getUTCHours()) + ":"
            + pad(local.getUTCMinutes()) + ":" + pad(local.getUTCSeconds())
            + (match[7] || "") + " HKT"
    }
    function kindLabel(value) { return t("outage_" + value) }
    function workflowLabel(value) { return t("outage_" + value) }
    function actionLabel(value) {
        if (value === "submit") return t("outage_submit")
        if (value === "save") return t("outage_save_turnout")
        if (value === "create") return t("outage_create_allocation")
        if (value === "amend") return t("outage_amend_allocation")
        return value || "—"
    }
    function findIndex(rows, key, value) {
        for (var index = 0; index < rows.length; index++)
            if (rows[index][key] === value) return index
        return -1
    }
    function rebuildOptions() {
        kindOptions = ["network", "backend", "database", "unknown"].map(function(value) {
            return {value: value, label: page.kindLabel(value)}
        })
        workflowOptions = ["count", "turnout", "allocation"].map(function(value) {
            return {value: value, label: page.workflowLabel(value)}
        })
        var actions = paperForm.workflow === "turnout" ? ["save", "submit"]
            : paperForm.workflow === "allocation" ? ["create", "amend"]
            : ["submit"]
        actionOptions = actions.map(function(value) {
            return {value: value, label: page.actionLabel(value)}
        })
    }
    function requestSelect(id) {
        if (editorState.uncertain_save) return
        if (editorState.dirty || editorState.newer_revision) {
            pendingNewOutage = false
            pendingOutageId = id
            discardDialog.open()
            return
        }
        outages.loadOutage(id, false)
    }
    function requestNew() {
        if (editorState.uncertain_save) return
        if (editorState.dirty || editorState.newer_revision) {
            pendingNewOutage = true
            pendingOutageId = 0
            discardDialog.open()
            return
        }
        outages.loadOutage(0, false)
    }
    function continueAfterDiscard() {
        discardDialog.close()
        if (pendingNewOutage) {
            outages.loadOutage(0, true)
        } else {
            outages.loadOutage(pendingOutageId, true)
        }
    }
    function paperTarget(paper) {
        var target = paper.target || ({})
        var values = []
        if (target.scope_id) values.push(t("outage_target_scope") + " " + target.scope_id)
        if (target.round_id) values.push(t("outage_target_round") + " " + target.round_id)
        if (target.period_index !== undefined && target.period_index !== null)
            values.push(t("outage_target_period") + " " + target.period_index)
        if (target.counter_id) values.push(t("outage_target_counter") + " " + target.counter_id)
        if (target.allocation_id) values.push(t("outage_target_allocation") + " " + target.allocation_id)
        return values.join(" · ") || "—"
    }
    function canonicalRecord(paper) {
        var receipt = (paper.reentry || {}).record || ({})
        return receipt.record || receipt
    }
    function receiptFacts(paper) {
        var record = page.canonicalRecord(paper)
        var facts = [
            t("outage_receipt_record") + " " + page.exact(record.id),
            t("outage_receipt_revision") + " " + page.exact(record.revision),
            t("outage_receipt_status") + " " + page.t("outage_receipt_status_" + record.status)
        ]
        if (record.workflow === "count" || paper.workflow === "count") {
            if (record.round_number !== undefined)
                facts.push(page.t("outage_target_round") + " " + page.exact(record.round_number))
        } else if (paper.workflow === "turnout") {
            facts.push(page.t("outage_target_period") + " " + page.exact(record.period_index))
            facts.push(page.t("outage_receipt_hourly") + " " + page.quantity(record, "supplied_hourly"))
            facts.push(page.t("outage_receipt_cumulative") + " " + page.quantity(record, "supplied_cumulative"))
        } else if (paper.workflow === "allocation") {
            var counter = record.counter || ({})
            facts.push(page.t("outage_target_counter") + " " + page.exact(counter.code || counter.id))
            facts.push(page.t("allocation_quantity") + " " + page.quantity(record, "quantity"))
            facts.push(page.t("outage_receipt_event") + " " + page.timeHkt(record.event_at))
        }
        return facts.join(" · ")
    }
    function receiptQuantities(paper) {
        var record = page.canonicalRecord(paper)
        var lines = []
        if (paper.workflow === "count") {
            ;(record.candidate_votes || []).forEach(function(row) {
                lines.push({caption: page.t("outage_receipt_candidate") + " " + row.name,
                    value: page.quantity(row, "quantity")})
            })
            ;(record.invalid_papers || []).forEach(function(row) {
                var label = row["label_" + page.locale] || row.name || row.reason_id
                lines.push({caption: page.t("outage_receipt_invalid") + " " + label,
                    value: page.quantity(row, "quantity")})
            })
            for (var key of ["questionable_quantity", "actual_counted_quantity",
                    "initial_valid_quantity", "clearly_invalid_quantity",
                    "initial_accounted_quantity"]) {
                if (record[key] !== undefined)
                    lines.push({caption: page.t("outage_receipt_" + key),
                        value: page.quantity(record, key)})
            }
        } else if (paper.workflow === "turnout") {
            for (var turnoutKey of ["supplied_hourly", "supplied_cumulative",
                    "derived_hourly", "derived_cumulative_start", "derived_cumulative_end"]) {
                lines.push({caption: page.t("outage_receipt_" + turnoutKey),
                    value: page.quantity(record, turnoutKey)})
            }
        } else if (paper.workflow === "allocation") {
            lines.push({caption: page.t("allocation_quantity"), value: page.quantity(record, "quantity")})
            lines.push({caption: page.t("outage_receipt_serials"),
                value: page.exact(record.serial_from) + " – " + page.exact(record.serial_to)})
        }
        return lines
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function updatePaperOptions() { page.rebuildOptions() }

    onWordsChanged: rebuildOptions()
    onLocaleChanged: rebuildOptions()
    Component.onCompleted: rebuildOptions()
    Connections {
        target: page.outages
        function onStateChanged() { page.updatePaperOptions() }
        function onErasePassword() { approvalPassword.clear() }
    }

    component Heading: Label {
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        font.pixelSize: 20
        font.weight: Font.Medium
        color: "#25344b"
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        Layout.fillWidth: true
        spacing: 5
        FormCaption { text: detail.caption }
        Label {
            text: detail.value
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            color: "#25344b"
            font.pixelSize: 15
            Layout.fillWidth: true
        }
    }
    component TextEntry: ColumnLayout {
        id: entry
        required property string caption
        required property string fieldName
        required property string value
        property bool paperField: false
        property bool isEditable: false
        property bool privateInput: false
        property int inputEchoMode: TextInput.Normal
        property alias textValue: field.text
        function clear() { field.clear() }
        Layout.fillWidth: true
        spacing: 6
        FormCaption { text: entry.caption }
        TextField {
            id: field
            Layout.fillWidth: true
            implicitHeight: 48
            text: entry.value
            selectByMouse: true
            echoMode: entry.inputEchoMode
            enabled: entry.isEditable && !page.working
            readOnly: !entry.isEditable
            Accessible.name: entry.caption
            onTextEdited: {
                if (entry.privateInput) return
                if (entry.paperField) page.outages.setPaperField(entry.fieldName, text)
                else page.outages.setField(entry.fieldName, text)
            }
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                if (field.activeFocus) page.reveal(field)
            })
            background: Rectangle {
                radius: 8
                color: "white"
                border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
                border.width: field.activeFocus ? 2 : 1
            }
        }
    }
    component NotesArea: ColumnLayout {
        id: area
        required property string caption
        required property string fieldName
        required property string value
        property bool paperField: false
        property bool isEditable: false
        property bool privateInput: false
        property alias textValue: notes.text
        Layout.fillWidth: true
        spacing: 6
        FormCaption { text: area.caption }
        TextArea {
            id: notes
            Layout.fillWidth: true
            implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
            text: area.value
            textFormat: TextEdit.PlainText
            wrapMode: TextEdit.WordWrap
            clip: true
            selectByMouse: true
            enabled: area.isEditable && !page.working
            readOnly: !area.isEditable
            leftPadding: 12
            rightPadding: 12
            topPadding: 12
            bottomPadding: 12
            topInset: 0
            Accessible.name: area.caption
            Keys.priority: Keys.BeforeItem
            Keys.onTabPressed: event => { page.moveFocus(notes, true); event.accepted = true }
            Keys.onBacktabPressed: event => { page.moveFocus(notes, false); event.accepted = true }
            onTextChanged: if (activeFocus) {
                if (area.privateInput) return
                if (area.paperField) page.outages.setPaperField(area.fieldName, text)
                else page.outages.setField(area.fieldName, text)
            }
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                if (notes.activeFocus) page.reveal(notes)
            })
            background: Rectangle {
                radius: 8
                color: "white"
                border.color: notes.activeFocus ? "#1967d2" : "#a7b2c2"
                border.width: notes.activeFocus ? 2 : 1
            }
        }
    }
    component Choice: ColumnLayout {
        id: choice
        required property string caption
        required property var modelRows
        required property string value
        required property string fieldName
        property bool paperField: false
        property bool isEditable: false
        Layout.fillWidth: true
        spacing: 6
        FormCaption { text: choice.caption }
        ComboBox {
            id: picker
            Layout.fillWidth: true
            textRole: "label"
            model: choice.modelRows
            currentIndex: page.findIndex(choice.modelRows, "value", choice.value)
            enabled: choice.isEditable && !page.working
            Accessible.name: choice.caption
            onActivated: index => {
                var value = choice.modelRows[index].value
                if (choice.paperField) page.outages.setPaperField(choice.fieldName, value)
                else page.outages.setField(choice.fieldName, value)
            }
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                if (picker.activeFocus) page.reveal(picker)
            })
        }
    }
    component ActionButton: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, actionLabel.implicitHeight + 24)
        contentItem: Text {
            id: actionLabel
            text: action.text
            textFormat: Text.PlainText
            font: action.font
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: action.enabled ? (action.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("outage_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.working
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "outagesRefresh"
            text: page.t("outage_refresh")
            flat: true
            highlighted: false
            enabled: !!page.editorState.station_id && !page.working
            onClicked: page.outages.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("outage_intro") }
    FormNotice {
        objectName: "outagesNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        autoReveal: !discardDialog.visible
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        visible: !!page.editorState.uncertain_save
        implicitHeight: uncertainColumn.implicitHeight + 40
        ColumnLayout {
            id: uncertainColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 10
            Heading { text: page.t("outage_pending_request") }
            FormCaption {
                text: page.t("outage_uncertain_hint") + " · "
                    + page.t("outage_pending_request") + " "
                    + (page.editorState.pending_request_id || "—")
                color: "#8a5c16"
            }
            Detail {
                caption: page.t("outage_current_revision")
                value: {
                    var current = (page.editorState.items || []).find(function(row) {
                        return row.id === page.selected.id
                    }) || ({})
                    return page.t("outage_revision") + " " + page.exact(current.revision)
                        + " · " + page.t("outage_papers") + " " + page.exact(current.paper_count)
                        + " · " + page.t("outage_pending") + " "
                        + page.exact(current.pending_paper_count)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    objectName: "outageRetryOutage"
                    visible: page.editorState.pending_kind !== "existing_receipt_link"
                        && page.operational && !page.editorState.selected_paper_id
                        && !page.paperForm.paper_reference
                    text: page.t("outage_retry_outage")
                    enabled: !!page.editorState.pending_request_id && !page.working
                    onClicked: page.outages.save()
                }
                ActionButton {
                    objectName: "outageRetryPaper"
                    visible: page.editorState.pending_kind !== "existing_receipt_link"
                        && page.operational && !!page.selected.id
                        && (!!page.editorState.selected_paper_id || !!page.paperForm.paper_reference)
                    text: page.t("outage_retry_paper")
                    enabled: !!page.editorState.pending_request_id && !page.working
                    onClicked: page.outages.savePaper()
                }
                ActionButton {
                    objectName: "outageRetryExistingReceipt"
                    visible: page.editorState.pending_kind === "existing_receipt_link"
                    text: page.t("outage_existing_receipt_retry")
                    enabled: !!page.editorState.pending_request_id && !page.working
                    onClicked: page.outages.linkExistingReceipt()
                }
                ActionButton {
                    objectName: "outageRetryReconciliation"
                    visible: page.editorState.role === "supervisor"
                    text: page.t("outage_retry_approval")
                    enabled: !!page.editorState.pending_request_id && !page.working
                    onClicked: page.outages.approveReconciliation(approvalPassword.textValue,
                        approvalReason.textValue)
                }
            }
            FormButton {
                objectName: "outageUncertainRefresh"
                text: page.t("outage_refresh")
                flat: true
                highlighted: false
                enabled: !!page.editorState.station_id && !page.working
                onClicked: page.outages.refresh()
                onReveal: control => page.reveal(control)
            }
        }
    }
    FormCaption { visible: !page.editorState.station_id; text: page.t("select_station") }
    FormCaption { visible: page.editorState.station_id; text: page.t("outage_station") + " " + page.editorState.station_id }
    FormCaption { visible: !page.outageEditable; text: page.t("outage_read_only") }
    FormCaption {
        visible: !!page.editorState.newer_revision
        text: page.t("outage_newer_revision")
        color: "#8a5c16"
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: listColumn.implicitHeight + 40
        ColumnLayout {
            id: listColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Heading { text: page.t("outage_list") }
                ActionButton {
                    objectName: "outageNew"
                    text: page.t("outage_new")
                    highlighted: true
                    enabled: page.outageEditable && !page.editorState.uncertain_save
                    onClicked: page.requestNew()
                }
            }
            FormCaption {
                visible: !(page.editorState.items || []).length
                text: page.t("outage_empty")
            }
            Repeater {
                model: page.editorState.items || []
                delegate: ActionButton {
                    required property var modelData
                    objectName: "outageOption_" + modelData.id
                    text: "#" + modelData.id + " · " + modelData.reference + " · "
                        + page.kindLabel(modelData.kind) + " · " + page.timeHkt(modelData.started_at)
                        + " – " + page.timeHkt(modelData.ended_at) + " · "
                        + page.t("outage_revision") + " " + modelData.revision + " · "
                        + page.t("outage_papers") + " " + modelData.paper_count + " / "
                        + page.t("outage_pending") + " " + modelData.pending_paper_count
                    highlighted: page.selected.id === modelData.id
                    enabled: !page.working && !page.editorState.uncertain_save
                    onClicked: page.requestSelect(modelData.id)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: outageEditor.implicitHeight + 40
        ColumnLayout {
            id: outageEditor
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("outage_details") }
            Detail {
                visible: !!page.selected.id
                caption: page.t("outage_revision")
                value: page.exact(page.selected.revision) + " · " + page.t("outage_actor") + " "
                    + page.exact(page.selected.actor_id) + " · " + page.t("outage_server_entered")
                    + " " + page.timeHkt(page.selected.entered_at)
            }
            TextEntry {
                objectName: "outageReference"
                caption: page.t("outage_reference")
                fieldName: "reference"
                value: page.form.reference || ""
                isEditable: page.outageEditable
            }
            Choice {
                objectName: "outageKind"
                caption: page.t("outage_kind")
                modelRows: page.kindOptions
                value: page.form.kind || "network"
                fieldName: "kind"
                isEditable: page.outageEditable
            }
            TextEntry {
                objectName: "outageStartedAt"
                caption: page.t("outage_started")
                fieldName: "started_at"
                value: page.form.started_at || ""
                isEditable: page.outageEditable
            }
            TextEntry {
                objectName: "outageEndedAt"
                caption: page.t("outage_ended")
                fieldName: "ended_at"
                value: page.form.ended_at || ""
                isEditable: page.outageEditable
            }
            FormCaption { text: page.t("outage_time_hint") }
            NotesArea {
                objectName: "outageNotes"
                caption: page.t("outage_notes")
                fieldName: "notes"
                value: page.form.notes || ""
                isEditable: page.outageEditable
            }
            TextEntry {
                objectName: "outageAmendmentReason"
                visible: !!page.selected.id
                caption: page.t("outage_reason")
                fieldName: "amendment_reason"
                value: page.form.amendment_reason || ""
                isEditable: page.outageEditable
            }
            FormCaption {
                visible: !!page.editorState.dirty
                text: page.t("outage_dirty_hint")
                color: "#8a5c16"
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    objectName: "outageSave"
                    text: page.selected.id ? page.t("outage_amend") : page.t("outage_save")
                    highlighted: true
                    enabled: page.outageEditable && !!page.editorState.dirty
                    onClicked: page.outages.save()
                }
                ActionButton {
                    objectName: "outageReload"
                    text: page.t("outage_reload")
                    visible: !!page.selected.id && (page.editorState.dirty || page.editorState.newer_revision)
                    enabled: !page.working && !page.editorState.uncertain_save
                    onClicked: {
                        if (page.editorState.dirty) {
                            page.pendingNewOutage = false
                            page.pendingOutageId = page.selected.id
                            discardDialog.open()
                        } else page.outages.discardAndReload()
                    }
                }
            }
            Repeater {
                model: page.editorState.history || []
                delegate: Detail {
                    required property var modelData
                    caption: page.t("outage_revision") + " " + page.exact(modelData.revision)
                    value: page.kindLabel(modelData.kind) + " · " + modelData.reference + " · "
                        + page.timeHkt(modelData.started_at) + " – " + page.timeHkt(modelData.ended_at)
                        + " · " + page.t("outage_actor") + " " + page.exact(modelData.actor_id)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: paperColumn.implicitHeight + 40
        ColumnLayout {
            id: paperColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Heading { text: page.t("outage_papers") }
                ActionButton {
                    objectName: "outagePaperNew"
                    text: page.t("outage_paper_new")
                    highlighted: true
                    enabled: page.active && page.operational && !page.working
                        && !page.editorState.dirty && !page.editorState.uncertain_save
                    onClicked: page.outages.beginPaper(0)
                }
            }
            FormCaption {
                visible: !(page.selected.paper_records || []).length
                text: page.t("outage_empty")
            }
            Repeater {
                model: page.selected.paper_records || []
                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 8
                    ActionButton {
                        objectName: "outagePaperOption_" + parent.modelData.id
                        text: page.t("outage_paper_reference") + " · " + parent.modelData.paper_reference
                            + " · " + page.t("outage_" + parent.modelData.status)
                            + " · " + page.workflowLabel(parent.modelData.workflow) + " / "
                            + page.actionLabel(parent.modelData.action) + " · "
                            + page.t("outage_paper_revision") + " " + parent.modelData.revision
                        highlighted: page.editorState.selected_paper_id === parent.modelData.id
                        enabled: !page.working
                        onClicked: page.outages.beginPaper(parent.modelData.id)
                    }
                    Detail {
                        caption: page.t("outage_original_time")
                        value: page.timeHkt(parent.modelData.original_event_at) + " · "
                            + page.paperTarget(parent.modelData)
                    }
                    Detail {
                        caption: page.t("outage_paper_server_time")
                        value: page.timeHkt(parent.modelData.entered_at) + " · "
                            + page.t("outage_paper_actor") + " " + page.exact(parent.modelData.actor_id)
                    }
                    Detail {
                        visible: !!parent.modelData.notes
                        caption: page.t("outage_paper_notes")
                        value: parent.modelData.notes
                    }
                    Detail {
                        visible: !!parent.modelData.amendment_reason
                        caption: page.t("outage_paper_reason")
                        value: parent.modelData.amendment_reason
                    }
                    Repeater {
                        model: parent.modelData.history || []
                        delegate: Detail {
                            required property var modelData
                            caption: page.t("outage_paper_revision") + " "
                                + page.exact(modelData.revision)
                            value: page.t("outage_paper_actor") + " "
                                + page.exact(modelData.actor_id) + " · "
                                + page.timeHkt(modelData.entered_at) + " · "
                                + page.exact(modelData.amendment_reason)
                        }
                    }
                    Detail {
                        visible: parent.modelData.status === "entered"
                        caption: page.t("outage_reentry")
                        value: page.t("outage_receipt_request") + " "
                            + page.exact((parent.modelData.reentry || {}).request_id) + " · "
                            + page.t("outage_receipt_actor") + " "
                            + page.exact((parent.modelData.reentry || {}).actor_id) + " · "
                            + page.t("outage_receipt_reentered_at") + " "
                            + page.timeHkt((parent.modelData.reentry || {}).entered_at) + " · "
                            + page.receiptFacts(parent.modelData)
                    }
                    Detail {
                        visible: !!(parent.modelData.reentry || {}).link
                        caption: page.t("outage_existing_link_metadata")
                        value: {
                            var link = (parent.modelData.reentry || {}).link || ({})
                            return page.t("outage_existing_link_request") + " "
                                + page.exact(link.request_id) + " · "
                                + page.t("outage_existing_receipt_reason") + " "
                                + page.exact(link.reason) + " · " + page.timeHkt(link.linked_at)
                                + " · " + page.t("outage_actor") + " " + page.exact(link.actor_id)
                        }
                    }
                    Repeater {
                        model: parent.modelData.status === "entered"
                            ? page.receiptQuantities(parent.modelData) : []
                        delegate: Detail {
                            required property var modelData
                            caption: modelData.caption
                            value: modelData.value
                        }
                    }
                }
            }
            FormCaption {
                visible: !!page.editorState.paper_editable
                text: page.editorState.selected_paper_id
                    ? page.t("outage_paper_amend") : page.t("outage_paper_new")
            }
            TextEntry {
                objectName: "outagePaperReference"
                visible: !page.editorState.selected_paper_id
                caption: page.t("outage_paper_reference")
                fieldName: "paper_reference"
                value: page.paperForm.paper_reference || ""
                paperField: true
                isEditable: page.paperEditable
            }
            Choice {
                objectName: "outagePaperWorkflow"
                visible: !page.editorState.selected_paper_id
                caption: page.t("outage_workflow")
                modelRows: page.workflowOptions
                value: page.paperForm.workflow || "count"
                fieldName: "workflow"
                paperField: true
                isEditable: page.paperEditable
            }
            Choice {
                objectName: "outagePaperAction"
                visible: !page.editorState.selected_paper_id
                caption: page.t("outage_action")
                modelRows: page.actionOptions
                value: page.paperForm.action || "submit"
                fieldName: "action"
                paperField: true
                isEditable: page.paperEditable
            }
            TextEntry {
                objectName: "outagePaperOriginalTime"
                caption: page.t("outage_original_time")
                fieldName: "original_event_at"
                value: page.paperForm.original_event_at || ""
                paperField: true
                isEditable: page.paperEditable
            }
            FormCaption { visible: !!page.editorState.paper_editable; text: page.t("outage_original_time_hint") }
            TextEntry {
                objectName: "outagePaperScopeId"
                visible: !page.editorState.selected_paper_id && page.paperForm.workflow === "count"
                caption: page.t("outage_target_scope")
                fieldName: "target_scope_id"
                value: page.paperForm.target_scope_id || ""
                paperField: true
                isEditable: page.paperEditable
            }
            TextEntry {
                objectName: "outagePaperRoundId"
                visible: !page.editorState.selected_paper_id && page.paperForm.workflow === "count"
                caption: page.t("outage_target_round")
                fieldName: "target_round_id"
                value: page.paperForm.target_round_id || ""
                paperField: true
                isEditable: page.paperEditable
            }
            TextEntry {
                objectName: "outagePaperPeriodIndex"
                visible: !page.editorState.selected_paper_id && page.paperForm.workflow === "turnout"
                caption: page.t("outage_target_period")
                fieldName: "target_period_index"
                value: page.paperForm.target_period_index || ""
                paperField: true
                isEditable: page.paperEditable
            }
            TextEntry {
                objectName: "outagePaperCounterId"
                visible: !page.editorState.selected_paper_id && page.paperForm.workflow === "allocation"
                caption: page.t("outage_target_counter")
                fieldName: "target_counter_id"
                value: page.paperForm.target_counter_id || ""
                paperField: true
                isEditable: page.paperEditable
            }
            TextEntry {
                objectName: "outagePaperAllocationId"
                visible: !page.editorState.selected_paper_id && page.paperForm.workflow === "allocation"
                    && page.paperForm.action === "amend"
                caption: page.t("outage_target_allocation")
                fieldName: "target_allocation_id"
                value: page.paperForm.target_allocation_id || ""
                paperField: true
                isEditable: page.paperEditable
            }
            NotesArea {
                objectName: "outagePaperNotes"
                visible: !!page.editorState.paper_editable
                caption: page.t("outage_paper_notes")
                fieldName: "notes"
                value: page.paperForm.notes || ""
                paperField: true
                isEditable: page.paperEditable
            }
            TextEntry {
                objectName: "outagePaperAmendmentReason"
                visible: page.editorState.paper_editable && !!page.editorState.selected_paper_id
                caption: page.t("outage_paper_reason")
                fieldName: "amendment_reason"
                value: page.paperForm.amendment_reason || ""
                paperField: true
                isEditable: page.paperEditable
            }
            ActionButton {
                objectName: "outagePaperSave"
                visible: !!page.editorState.paper_editable
                text: page.editorState.selected_paper_id
                    ? page.t("outage_paper_amend") : page.t("outage_paper_save")
                highlighted: true
                enabled: page.paperEditable && !!page.editorState.dirty
                onClicked: page.outages.savePaper()
            }
        }
    }
    FormPanel {
        visible: page.matchingAllowed
        implicitHeight: existingReceiptColumn.implicitHeight + 40
        ColumnLayout {
            id: existingReceiptColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("outage_existing_receipt_title") }
            FormCaption { text: page.t("outage_existing_receipt_hint") }
            Detail {
                caption: page.t("outage_paper_reference")
                value: page.exact(page.matchingPaper.paper_reference) + " · "
                    + page.paperTarget(page.matchingPaper)
            }
            FormCaption { text: page.t("outage_existing_receipt_request") }
            FormField {
                objectName: "outageExistingRequestId"
                text: page.existingReceipt.request_id || ""
                Accessible.name: page.t("outage_existing_receipt_request")
                working: page.working || !!page.editorState.uncertain_save
                maximumLength: 100
                onTextEdited: page.outages.setExistingReceiptField("request_id", text)
                onReveal: control => page.reveal(control)
            }
            ActionButton {
                objectName: "outageExistingReceiptCheck"
                text: page.t("outage_existing_receipt_check")
                enabled: !page.working && !page.editorState.uncertain_save
                    && !!page.existingReceipt.request_id
                onClicked: page.outages.checkExistingReceipt()
            }
            ColumnLayout {
                objectName: "outageExistingReceiptSummary"
                visible: (page.existingReceipt.checked || {}).status === "committed"
                Layout.fillWidth: true
                spacing: 10
                Detail {
                    caption: page.t("outage_existing_receipt_checked")
                    value: page.receiptFacts(page.checkedPaper)
                }
                Detail {
                    caption: page.t("outage_original_time")
                    value: page.timeHkt(page.matchingPaper.original_event_at)
                }
                Detail {
                    caption: page.t("outage_existing_receipt_server_time")
                    value: {
                        var record = page.canonicalRecord(page.checkedPaper)
                        return page.timeHkt(record.revision_entered_at || record.entered_at)
                    }
                }
                Repeater {
                    model: page.receiptQuantities(page.checkedPaper)
                    delegate: Detail {
                        required property var modelData
                        caption: modelData.caption
                        value: modelData.value
                    }
                }
            }
            FormCaption { text: page.t("outage_existing_receipt_reason") }
            FormField {
                objectName: "outageExistingReceiptReason"
                text: page.existingReceipt.reason || ""
                Accessible.name: page.t("outage_existing_receipt_reason")
                working: page.working || !!page.editorState.uncertain_save
                maximumLength: 2000
                onTextEdited: page.outages.setExistingReceiptField("reason", text)
                onReveal: control => page.reveal(control)
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    objectName: "outageExistingReceiptLink"
                    text: page.t("outage_existing_receipt_link")
                    highlighted: true
                    enabled: !page.working && !page.editorState.uncertain_save
                        && (page.existingReceipt.checked || {}).status === "committed"
                        && !!(page.existingReceipt.reason || "").trim()
                    onClicked: page.outages.linkExistingReceipt()
                }
                FormButton {
                    objectName: "outageExistingReceiptClear"
                    text: page.t("outage_existing_receipt_clear")
                    flat: true
                    highlighted: false
                    enabled: !page.working && !page.editorState.uncertain_save
                    onClicked: page.outages.clearExistingReceipt()
                    onReveal: control => page.reveal(control)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id && page.selected.paper_records
            && page.selected.paper_records.length > 0
        implicitHeight: reconciliation.implicitHeight + 40
        ColumnLayout {
            id: reconciliation
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("outage_reconcile") }
            FormCaption { text: page.t("outage_reconcile_hint") }
            Detail {
                caption: page.t("outage_reconciled")
                value: page.selected.reconciled && (page.selected.reconciliation || {}).is_current
                    ? page.t("outage_reconciled") + " · " + page.t("outage_reconciliation_revision") + " "
                        + page.exact(page.selected.reconciliation.revision)
                    : page.t("outage_not_reconciled")
            }
            Repeater {
                model: page.selected.reconciliation_history || []
                delegate: Detail {
                    required property var modelData
                    caption: page.t("outage_reconciliation_history") + " · "
                        + page.t("outage_reconciliation_revision") + " " + page.exact(modelData.revision)
                    value: page.t(modelData.valid ? "outage_reconciled" : "outage_not_reconciled")
                        + " · " + page.t("outage_actor") + " " + page.exact(modelData.actor_id)
                        + " · " + page.timeHkt(modelData.accepted_at)
                }
            }
            TextEntry {
                id: approvalPassword
                objectName: "outageApprovalPassword"
                visible: page.editorState.role === "supervisor"
                caption: page.t("outage_supervisor_password")
                fieldName: ""
                value: ""
                isEditable: page.active && !page.working
                privateInput: true
                inputEchoMode: TextInput.Password
                // Keep the password in this ephemeral QML field; never send it to state.
            }
            NotesArea {
                id: approvalReason
                objectName: "outageApprovalReason"
                visible: page.editorState.role === "supervisor"
                caption: page.t("outage_reconcile_reason")
                fieldName: ""
                value: ""
                isEditable: page.active && !page.working
                privateInput: true
            }
            ActionButton {
                objectName: "outageApproveReconciliation"
                visible: page.editorState.role === "supervisor"
                text: page.t("outage_approve")
                highlighted: true
                enabled: page.active && !page.working && !page.editorState.dirty
                    && !page.editorState.newer_revision
                    && (page.selected.paper_records || []).length > 0
                    && (page.selected.paper_records || []).every(function(paper) {
                        return paper.status === "entered"
                    })
                onClicked: page.outages.approveReconciliation(approvalPassword.textValue,
                    approvalReason.textValue)
            }
        }
    }

    FormPanel {
        objectName: "outageReportPanel"
        visible: !!page.selected.id
        implicitHeight: reportColumn.implicitHeight + 40
        ColumnLayout {
            id: reportColumn
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("outage_report") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 800 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 12
                ActionButton {
                    objectName: "outageReportPreview"
                    text: page.t("outage_report_preview")
                    enabled: !page.working && !page.editorState.dirty
                        && !page.editorState.newer_revision && !page.editorState.uncertain_save
                    onClicked: page.outages.previewReport(page.locale)
                }
                ActionButton {
                    objectName: "outageReportExportPdf"
                    text: page.t("outage_report_export_pdf")
                    enabled: !page.working && !page.editorState.dirty
                        && !page.editorState.newer_revision && !page.editorState.uncertain_save
                    onClicked: page.exportReport("pdf")
                }
                ActionButton {
                    objectName: "outageReportExportCsv"
                    text: page.t("outage_report_export_csv")
                    enabled: !page.working && !page.editorState.dirty
                        && !page.editorState.newer_revision && !page.editorState.uncertain_save
                    onClicked: page.exportReport("csv")
                }
            }
            Label {
                objectName: "outageReportPreviewText"
                visible: page.editorState.report.locale === page.locale
                text: page.editorState.report_text || ""
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
                color: "#25344b"
            }
            FormCaption {
                text: page.editorState.export_path || ""
                visible: !!text
            }
        }
    }
    FileDialog {
        id: exportDialog
        objectName: "outageReportExportDialog"
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.outages.downloadReport(
            page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }

    Dialog {
        id: discardDialog
        modal: true
        title: page.t("outage_confirm_discard_title")
        standardButtons: Dialog.NoButton
        anchors.centerIn: Overlay.overlay
        width: Math.min(page.width - 32, 520)
        contentItem: ColumnLayout {
            spacing: 14
            Label {
                Layout.fillWidth: true
                text: page.t("outage_confirm_discard")
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    text: page.t("outage_keep_editing")
                    highlighted: false
                    onClicked: discardDialog.close()
                }
                ActionButton {
                    text: page.t("outage_discard_continue")
                    highlighted: true
                    onClicked: page.continueAfterDiscard()
                }
            }
        }
    }
}
