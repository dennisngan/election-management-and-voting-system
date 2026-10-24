pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var countingScopes
    required property var words
    property string locale: "tc"
    readonly property var editorState: countingScopes.state
    readonly property var context: editorState.context || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.forms || ({})
    readonly property bool editable: editorState.role === "counting_officer"
        && !editorState.historical && !editorState.newer_revision
    readonly property bool working: editorState.busy || editorState.refreshing
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function hasBox(id) { return (editorState.selected_box_ids || []).indexOf(id) >= 0 }
    function stationName(row) {
        var station = row.station || {}
        return (station.code || "") + " · " + (station.name || "")
    }
    function boxLabel(row) {
        var origin = row.origin || {}
        var status = row.receipt || row.receipt_at || row.status === "received"
            ? t("counting_scope_box_received") : t("counting_scope_box_pending")
        return (row.box_reference || ("#" + row.id)) + " · "
            + ((origin.code || "") + " · " + (origin.name || "")) + " · " + status
            + " · " + t("revision") + " " + (row.revision || "—")
            + (row.scope_id && row.scope_id !== page.selected.id
                ? " · " + t("counting_scope_box_in_scope") + " #" + row.scope_id : "")
    }
    function frozenBoxLabel(row) {
        var origin = row.origin || {}
        var received = row.receipt || row.receipt_at || row.status === "received"
        return (row.box_reference || ("#" + row.id)) + " · "
            + (origin.code || "") + " · " + (origin.name || "")
            + " · " + t("revision") + " " + row.revision
            + " · " + (received ? t("counting_scope_box_received") : t("counting_scope_box_pending"))
    }
    function sourceOptions(source) {
        var record = source.record || {}
        var options = [{revision: 0, label: t("counting_scope_no_accounting_selected")}]
        if (record.revision)
            options.push({revision: record.revision,
                label: t("counting_scope_current_accounting").replace("%1", String(record.revision))
                    + " · " + t(record.status)})
        return options
    }
    function sourceIndex(source) {
        var options = sourceOptions(source)
        if (editorState.historical) return Math.max(0, options.length - 1)
        var wanted = (editorState.accounting_selection || {})[String(source.station.id)] || 0
        for (var index = 0; index < options.length; index++)
            if (options[index].revision === wanted) return index
        return 0
    }
    function historyOptions() {
        return (editorState.history || []).map(function(row) {
            return {revision: row.revision, label: page.t(row.status) + " · "
                + page.t("revision") + " " + row.revision + " · " + row.reference}
        })
    }
    function historyIndex() {
        var options = historyOptions()
        for (var index = 0; index < options.length; index++)
            if (options[index].revision === page.selected.revision) return index
        return -1
    }
    function blockerText(row) {
        var key = "counting_scope_blocker_" + row.code
        return words[key] || row.code
    }
    function estimate(row, key) {
        var display = row[key + "_display"]
        if (display !== undefined) return display
        return row[key] === undefined || row[key] === null ? "—" : String(row[key])
    }
    function exportReport(format) {
        if (!selected.id || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/counting-scope-"
            + selected.id + "-revision-" + selected.revision + "-" + locale + "." + format
        exportDialog.open()
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, actionText.implicitHeight + 24)
        contentItem: Text {
            id: actionText
            text: action.text
            font: action.font
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: action.enabled ? (action.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component TextEntry: TextField {
        id: entry
        property string caption: ""
        Layout.fillWidth: true
        implicitHeight: 48
        placeholderText: caption
        Accessible.name: caption
        enabled: page.editable && !page.editorState.busy
        readOnly: !page.editable
        selectByMouse: true
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (entry.activeFocus) page.reveal(entry)
        })
        background: Rectangle {
            radius: 8; color: "white"
            border.color: entry.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: entry.activeFocus ? 2 : 1
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading {
            objectName: "countingScopesTitle"
            text: page.t("counting_scopes_title")
            font.pixelSize: 28
        }
        BusyIndicator {
            running: page.working
            visible: running
            implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "countingScopesRefresh"
            text: page.t("refresh")
            flat: true; highlighted: false
            enabled: !!page.editorState.station_id && !page.working
            onClicked: page.countingScopes.refresh()
            onReveal: control => page.reveal(control)
        }
        FormButton {
            objectName: "countingScopeReload"
            text: page.t("counting_scope_reload")
            flat: true; highlighted: false
            visible: page.editorState.dirty || page.editorState.newer_revision
            enabled: !page.editorState.busy
            onClicked: discardDialog.open()
            onReveal: control => page.reveal(control)
        }
    }

    FormPanel {
        objectName: "countingScopeReportPanel"
        visible: !!page.selected.id
        implicitHeight: reportColumn.implicitHeight + 40
        ColumnLayout {
            id: reportColumn
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("counting_scope_report") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 800 ? 3 : 1
                columnSpacing: 12; rowSpacing: 12
                Action {
                    objectName: "countingScopePreview"
                    text: page.t("counting_scope_preview")
                    enabled: !page.editorState.busy && !page.editorState.dirty
                        && !page.editorState.newer_revision
                    onClicked: page.countingScopes.preview(page.locale)
                }
                Action {
                    objectName: "countingScopeExportPdf"
                    text: page.t("stock_export_pdf")
                    enabled: !page.editorState.busy && !page.editorState.dirty
                        && !page.editorState.newer_revision
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "countingScopeExportCsv"
                    text: page.t("stock_export_csv")
                    enabled: !page.editorState.busy && !page.editorState.dirty
                        && !page.editorState.newer_revision
                    onClicked: page.exportReport("csv")
                }
            }
            Label {
                objectName: "countingScopeReportPreview"
                visible: page.editorState.report.locale === page.locale
                text: page.editorState.report_text
                textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true; color: "#25344b"
            }
            FormCaption { text: page.editorState.export_path || ""; visible: !!text }
        }
    }
    Label {
        Layout.fillWidth: true
        text: page.t("counting_scopes_intro")
        textFormat: Text.PlainText
        color: "#52647d"
        wrapMode: Text.WordWrap
    }
    Rectangle {
        Layout.fillWidth: true
        radius: 10; color: "#f3f7fc"; border.color: "#d6e0ee"
        implicitHeight: contextColumn.implicitHeight + 28
        ColumnLayout {
            id: contextColumn
            anchors.fill: parent; anchors.margins: 14; spacing: 6
            Heading { text: page.t("counting_scope_context"); font.pixelSize: 16 }
            Label {
                Layout.fillWidth: true
                text: ((page.context.election || {}).name || "—") + " · "
                    + ((page.context.constituency || {}).name || "—") + " · "
                    + ((page.context.station || {}).code || "—") + " · "
                    + ((page.context.station || {}).name || "—")
                textFormat: Text.PlainText; color: "#25344b"; wrapMode: Text.WordWrap
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("counting_scope_list"); font.pixelSize: 18 }
        Action {
            objectName: "countingScopeNew"
            text: page.t("counting_scope_new")
            highlighted: true
            enabled: page.editorState.role === "counting_officer"
                && !page.editorState.busy && !page.editorState.dirty
            onClicked: page.countingScopes.newScope()
        }
    }
    Label {
        Layout.fillWidth: true
        visible: !page.editorState.scopes.length
        text: page.t("counting_scope_no_scopes")
        textFormat: Text.PlainText; color: "#52647d"
    }
    Repeater {
        model: page.editorState.scopes || []
        delegate: Action {
            required property var modelData
            objectName: "countingScopeOption_" + modelData.id
            text: modelData.reference + " · " + page.t(modelData.status) + " · "
                + page.t("revision") + " " + modelData.revision
            highlighted: modelData.id === page.selected.id
            enabled: !page.editorState.busy && !page.editorState.dirty
            onClicked: page.countingScopes.selectScope(modelData.id)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        visible: !!page.selected.id && page.editorState.history.length > 0
        Label {
            text: page.t("counting_scope_revision")
            textFormat: Text.PlainText; color: "#52647d"
        }
        ComboBox {
            id: scopeHistoryPicker
            objectName: "countingScopeHistory"
            Layout.fillWidth: true
            model: page.historyOptions()
            textRole: "label"
            currentIndex: page.historyIndex()
            enabled: !page.editorState.busy && !page.editorState.dirty
                && !page.editorState.newer_revision
            Accessible.name: page.t("counting_scope_revision")
            onActivated: index => page.countingScopes.loadRevision(model[index].revision)
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                if (scopeHistoryPicker.activeFocus) page.reveal(scopeHistoryPicker)
            })
        }
    }

    Label {
        objectName: "countingScopeError"
        Layout.fillWidth: true
        visible: !!page.editorState.error
        text: page.editorState.error === "counting_scope_validation"
            ? page.t("counting_scope_validation")
            : page.editorState.error === "counting_scope_not_ready"
                ? page.t("counting_scope_not_ready")
                : page.editorState.error === "unsaved_changes"
                    ? page.t("counting_scope_unsaved")
                    : page.t(page.editorState.error)
        textFormat: Text.PlainText; color: "#a12622"; wrapMode: Text.WordWrap
    }
    Label {
        Layout.fillWidth: true
        visible: !!page.editorState.notice
        text: page.t(page.editorState.notice)
        textFormat: Text.PlainText; color: "#176b45"; wrapMode: Text.WordWrap
    }
    Label {
        Layout.fillWidth: true
        visible: page.editorState.newer_revision
        text: page.t("counting_scope_stale")
        textFormat: Text.PlainText; color: "#9a5d00"; wrapMode: Text.WordWrap
    }
    Label {
        Layout.fillWidth: true
        visible: page.editorState.role !== "counting_officer"
        text: page.t("counting_scope_read_only")
        textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
    }
    Label {
        Layout.fillWidth: true
        visible: page.editorState.historical
        text: page.t("counting_scope_historical")
        textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
    }
    RowLayout {
        Layout.fillWidth: true
        TextEntry {
            objectName: "countingScopeReference"
            caption: page.t("counting_scope_reference")
            text: page.form.reference || ""
            readOnly: !!page.selected.id || !page.editable
            onTextEdited: page.countingScopes.setForm("reference", text)
        }
        TextEntry {
            objectName: "countingScopeEventAt"
            caption: page.t("counting_scope_event_at")
            text: page.form.event_at || ""
            onTextEdited: page.countingScopes.setForm("event_at", text)
        }
    }

    Heading { text: page.t("counting_scope_boxes"); font.pixelSize: 18 }
    Repeater {
        model: page.editorState.boxes || []
        delegate: CheckBox {
            id: boxControl
            required property var modelData
            objectName: "countingScopeBox_" + modelData.id
            Layout.fillWidth: true
            text: page.boxLabel(modelData)
            checked: page.hasBox(modelData.id)
            enabled: page.editable && !page.editorState.busy
                && (!modelData.scope_id || modelData.scope_id === page.selected.id)
            Accessible.name: text
            onToggled: page.countingScopes.setBoxSelected(modelData.id, checked)
            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                if (boxControl.activeFocus) page.reveal(boxControl)
            })
            contentItem: Text {
                text: parent.text; textFormat: Text.PlainText
                font: parent.font; color: parent.enabled ? "#25344b" : "#65758b"
                wrapMode: Text.WordWrap
                leftPadding: parent.indicator.width + parent.spacing
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    Heading {
        text: page.t("counting_scope_frozen_box_basis")
        font.pixelSize: 16
        visible: (page.selected.box_basis || []).length > 0
    }
    Repeater {
        model: page.selected.box_basis || []
        delegate: Label {
            required property var modelData
            objectName: "countingScopeFrozenBox_" + modelData.id
            Layout.fillWidth: true
            text: page.frozenBoxLabel(modelData)
            textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
        }
    }

    Heading { text: page.t("counting_scope_accounting"); font.pixelSize: 18 }
    Repeater {
        model: page.editorState.source_accounting || []
        delegate: RowLayout {
            required property var modelData
            objectName: "countingScopeSource_" + modelData.station.id
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: page.stationName(modelData)
                textFormat: Text.PlainText; color: "#25344b"; wrapMode: Text.WordWrap
            }
            ComboBox {
                id: accountingPicker
                objectName: "countingScopeAccounting_" + modelData.station.id
                Layout.preferredWidth: 340
                Layout.fillWidth: true
                model: page.sourceOptions(modelData)
                textRole: "label"
                currentIndex: page.sourceIndex(modelData)
                enabled: page.editable && !page.editorState.busy
                Accessible.name: page.t("counting_scope_accounting") + " · " + page.stationName(modelData)
                onActivated: index => page.countingScopes.chooseAccounting(
                    modelData.station.id, model[index].revision)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (accountingPicker.activeFocus) page.reveal(accountingPicker)
                })
            }
        }
    }
    Label {
        Layout.fillWidth: true
        visible: !page.editorState.source_accounting.length
        text: page.t("counting_scope_no_accounting")
        textFormat: Text.PlainText; color: "#52647d"
    }
    Heading { text: page.t("counting_scope_accounting_basis"); font.pixelSize: 16 }
    Repeater {
        model: page.selected.accounting_basis || []
        delegate: Rectangle {
            required property var modelData
            Layout.fillWidth: true
            radius: 8; color: "#f3f7fc"; border.color: "#d6e0ee"
            implicitHeight: basisColumn.implicitHeight + 24
            ColumnLayout {
                id: basisColumn
                anchors.fill: parent; anchors.margins: 12; spacing: 5
                Label {
                    Layout.fillWidth: true
                    objectName: "countingScopeP18Basis_" + modelData.station_id
                    text: page.t("counting_scope_p18_reference") + ": #" + modelData.id + " · "
                        + page.t("revision") + " " + modelData.revision + " · "
                        + page.t(modelData.status)
                    textFormat: Text.PlainText; color: "#25344b"; wrapMode: Text.WordWrap
                }
                Label {
                    Layout.fillWidth: true
                    objectName: "countingScopeP18Received_" + modelData.station_id
                    text: page.t("counting_scope_source_received_quantity") + ": "
                        + page.estimate(modelData.summary || {}, "received_quantity")
                    textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
                }
                Label {
                    Layout.fillWidth: true
                    objectName: "countingScopeP18Replacement_" + modelData.station_id
                    text: page.t("counting_scope_source_replacement_quantity") + ": "
                        + page.estimate(modelData.summary || {}, "replacement_unissued_quantity")
                    textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
                }
                Label {
                    Layout.fillWidth: true
                    text: page.t("counting_scope_stock_estimate") + ": "
                        + page.estimate(modelData.summary || {}, "estimated_box_from_stock_quantity")
                    textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
                }
                Label {
                    Layout.fillWidth: true
                    text: page.t("counting_scope_turnout_estimate") + ": "
                        + page.estimate(modelData.summary || {}, "estimated_box_from_turnout_quantity")
                    textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
                }
            }
        }
    }
    Label {
        Layout.fillWidth: true
        text: page.t("counting_scope_estimate_warning")
        textFormat: Text.PlainText; color: "#52647d"; wrapMode: Text.WordWrap
    }
    Repeater {
        model: page.selected.coverage || []
        delegate: ColumnLayout {
            required property var modelData
            Layout.fillWidth: true; spacing: 4
            Label {
                Layout.fillWidth: true
                text: page.stationName(modelData) + " · " + page.t("counting_scope_coverage")
                    + ": " + (modelData.scope_box_ids || []).length + "/"
                    + (modelData.source_box_ids || []).length
                textFormat: Text.PlainText; color: "#25344b"; wrapMode: Text.WordWrap
            }
            Label {
                objectName: "countingScopeCoverageWarning_" + modelData.station.id
                Layout.fillWidth: true
                visible: !modelData.all_source_boxes_in_scope
                text: page.t("counting_scope_whole_station_warning")
                textFormat: Text.PlainText; color: "#9a5d00"; wrapMode: Text.WordWrap
            }
        }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: width > 680 ? 2 : 1
        Heading { text: page.t("counting_scope_stock_estimate"); font.pixelSize: 15 }
        Label {
            objectName: "countingScopeStockEstimate"
            text: page.estimate(page.selected, "estimated_box_from_stock_quantity")
            textFormat: Text.PlainText; color: "#25344b"
        }
        Heading { text: page.t("counting_scope_turnout_estimate"); font.pixelSize: 15 }
        Label {
            objectName: "countingScopeTurnoutEstimate"
            text: page.estimate(page.selected, "estimated_box_from_turnout_quantity")
            textFormat: Text.PlainText; color: "#25344b"
        }
    }
    Heading { text: page.t("counting_scope_blockers"); font.pixelSize: 18 }
    Repeater {
        model: page.selected.blockers || []
        delegate: Label {
            required property var modelData
            required property int index
            objectName: "countingScopeBlocker_" + index
            Layout.fillWidth: true
            text: "• " + page.blockerText(modelData)
                + (modelData.box_id ? " · #" + modelData.box_id : "")
                + (modelData.station_id ? " · " + modelData.station_id : "")
            textFormat: Text.PlainText; color: "#9a5d00"; wrapMode: Text.WordWrap
        }
    }
    Label {
        Layout.fillWidth: true
        visible: !!page.selected.id && !(page.selected.blockers || []).length
        text: page.t("counting_scope_no_blockers")
        textFormat: Text.PlainText; color: "#176b45"; wrapMode: Text.WordWrap
    }

    FormCaption { text: page.t("counting_scope_notes"); Layout.fillWidth: true }
    TextArea {
        id: notesField
        objectName: "countingScopeNotes"
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        text: page.form.notes || ""
        enabled: page.editable && !page.editorState.busy
        readOnly: !page.editable
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WordWrap
        clip: true
        leftPadding: 12; rightPadding: 12; topPadding: 12; bottomPadding: 12; topInset: 0
        selectByMouse: true
        Accessible.name: page.t("counting_scope_notes")
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(notesField, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(notesField, false); event.accepted = true }
        onTextEdited: page.countingScopes.setForm("notes", text)
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (notesField.activeFocus) page.reveal(notesField)
        })
        background: Rectangle {
            radius: 8; color: "white"
            border.color: parent.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: parent.activeFocus ? 2 : 1
        }
    }
    FormCaption {
        visible: !!page.selected.id
        text: page.t("counting_scope_reason"); Layout.fillWidth: true
    }
    TextArea {
        id: reasonField
        objectName: "countingScopeReason"
        Layout.fillWidth: true
        visible: !!page.selected.id
        implicitHeight: Math.max(82, contentHeight + topPadding + bottomPadding)
        text: page.form.amendment_reason || ""
        enabled: page.editable && !page.editorState.busy && page.selected.status !== "draft"
        readOnly: !enabled
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WordWrap
        clip: true
        leftPadding: 12; rightPadding: 12; topPadding: 12; bottomPadding: 12; topInset: 0
        selectByMouse: true
        Accessible.name: page.t("counting_scope_reason")
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(reasonField, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(reasonField, false); event.accepted = true }
        onTextEdited: page.countingScopes.setForm("amendment_reason", text)
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (reasonField.activeFocus) page.reveal(reasonField)
        })
        background: Rectangle {
            radius: 8; color: "white"
            border.color: parent.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: parent.activeFocus ? 2 : 1
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Action {
            objectName: "countingScopeSave"
            text: page.t("counting_scope_save")
            highlighted: true
            visible: page.editorState.role === "counting_officer"
            enabled: page.editable && !page.editorState.busy && !page.editorState.newer_revision
            onClicked: page.countingScopes.save()
        }
        Action {
            objectName: "countingScopeSubmit"
            text: page.t("counting_scope_submit")
            highlighted: false
            visible: page.editorState.role === "counting_officer" && page.selected.status === "draft"
            enabled: page.editable && !page.editorState.busy && !page.editorState.dirty
                && !!page.selected.is_current && !!page.selected.source_current
                && !(page.selected.blockers || []).length
            onClicked: page.countingScopes.submit()
        }
    }
    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.countingScopes.download(
            page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "countingScopeDiscardDialog"
        focus: true
        message: page.t("counting_scope_discard")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.countingScopes.discardAndReload()
    }
}
