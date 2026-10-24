pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var accounting
    required property var words
    property string locale: "tc"
    readonly property var editorState: accounting.state
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var summary: editorState.summary || ({})
    readonly property var context: editorState.context || ({})
    readonly property var stock: editorState.stock_display || ({})
    readonly property var special: selected.special_papers || ({})
    readonly property var turnoutBasis: selected.turnout || ({})
    readonly property var turnoutRecord: editorState.turnout_display || ({})
    readonly property var sourceBasis: turnoutRecord.source_basis || ({})
    readonly property bool hasStation: !!editorState.station_id
    readonly property bool activeElection: !!context.election && context.election.status === "active"
    readonly property bool countingOfficer: editorState.role === "counting_officer"
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool editable: countingOfficer && activeElection && editorState.reviewed
        && !editorState.busy && !editorState.historical
    readonly property bool correctable: selected.status === "submitted" || selected.status === "approved"
    readonly property var specialOptions: (editorState.special_options || []).map(function(row) {
        return {id: row.id, revision: row.revision,
            label: "#" + row.id + " · " + page.t("revision") + " " + row.revision
                + " · " + page.time(row.event_at)
                + (row.source_current ? "" : " · " + page.t("accounting_source_stale"))}
    })
    readonly property var turnoutOptions: [{period: 0, revision: 0,
        label: page.t("accounting_no_turnout")}].concat((editorState.turnout_options || []).map(function(item) {
        var row = item.record
        return {period: row.period_index, revision: row.revision,
            label: "P(15) " + row.period_index + " · " + page.t("revision") + " " + row.revision
                + " · " + page.t(row.status) + " · " + page.time(row.end_at)}
    }))
    readonly property var quantityKeys: [
        "received_quantity", "ordinary_received_quantity", "ordinary_central_unissued_quantity",
        "ordinary_at_desks_quantity", "replacement_unissued_quantity", "tendered_unissued_quantity",
        "ordinary_issued_quantity", "replacement_issued_quantity", "spoilt_original_quantity",
        "tendered_issued_quantity", "retrieved_refused_quantity", "retrieved_found_quantity",
        "retrieved_held_quantity", "retrieved_unused_quantity", "never_issued_quantity",
        "estimated_box_from_stock_quantity", "estimated_box_from_turnout_quantity", "observed_counted_quantity"
    ]
    property int pendingRevision: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function time(value) { return value ? accounting.formatTime(value) : "—" }
    function exact(value) { return value === undefined || value === null ? "—" : String(value) }
    function basis(row) {
        return row && row.revision ? "#" + row.id + " · " + t("revision") + " " + row.revision
            + " · " + time(row.event_at) : "—"
    }
    function references(rows, key) {
        return (rows || []).map(function(row) {
            return "#" + row[key] + " · " + page.t("revision") + " " + row.revision
        }).join("; ") || "—"
    }
    function specialIndex() {
        for (let i = 0; i < specialOptions.length; i++)
            if (String(specialOptions[i].id) === form.special_paper_id
                    && String(specialOptions[i].revision) === form.special_paper_revision) return i
        return -1
    }
    function turnoutIndex() {
        for (let i = 1; i < turnoutOptions.length; i++)
            if (String(turnoutOptions[i].period) === form.turnout_period_index
                    && String(turnoutOptions[i].revision) === form.turnout_revision) return i
        return 0
    }
    function historyIndex() {
        for (let i = 0; i < editorState.history.length; i++)
            if (editorState.history[i].revision === selected.revision) return i
        return -1
    }
    function restorePickers() {
        specialPicker.currentIndex = Qt.binding(function() { return page.specialIndex() })
        turnoutPicker.currentIndex = Qt.binding(function() { return page.turnoutIndex() })
        historyPicker.currentIndex = Qt.binding(function() { return page.historyIndex() })
    }
    function load(revision) {
        var accepted = revision ? accounting.loadRevision(revision) : accounting.reload()
        if (!accepted && editorState.dirty && editorState.error === "unsaved_accounting_changes") {
            pendingRevision = revision
            discardDialog.open()
        }
        restorePickers()
    }
    function exportReport(format) {
        if (!selected.revision || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/p18-"
            + editorState.station_id + "-revision-" + selected.revision + "-" + locale + "." + format
        exportDialog.open()
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    component Heading: Label {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        font.pixelSize: 20
        font.weight: Font.Medium
        color: "#25344b"
        wrapMode: Text.WordWrap
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 6
        FormCaption { text: detail.caption }
        Label {
            objectName: detail.objectName ? detail.objectName + "Value" : ""
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 15
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }
    component ActionButton: FormButton {
        id: action
        Layout.fillWidth: true
        implicitWidth: 160
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
    component NotesArea: TextArea {
        id: field
        property string caption: ""
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WordWrap
        clip: true
        selectByMouse: true
        readOnly: !page.editable
        enabled: !page.editorState.busy
        leftPadding: 12; rightPadding: 12; topPadding: 12; bottomPadding: 12; topInset: 0
        Accessible.name: caption
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
        background: Rectangle {
            radius: 8; color: "white"
            border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: field.activeFocus ? 2 : 1
        }
    }
    component SourcePicker: ComboBox {
        id: picker
        Layout.fillWidth: true
        implicitHeight: Math.max(48, pickerText.implicitHeight + 24)
        textRole: "label"
        enabled: page.editable
        contentItem: Text {
            id: pickerText
            text: picker.displayText
            font: picker.font
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            color: picker.enabled ? "#25344b" : "#65758b"
            verticalAlignment: Text.AlignVCenter
            leftPadding: 12; rightPadding: 40
        }
        delegate: ItemDelegate {
            required property int index
            required property var modelData
            width: picker.width
            implicitHeight: Math.max(48, optionLabel.implicitHeight + 24)
            contentItem: Text {
                id: optionLabel
                text: modelData.label
                textFormat: Text.PlainText
                font: picker.font
                color: "#25344b"
                wrapMode: Text.WordWrap
            }
            highlighted: picker.highlightedIndex === index
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (picker.activeFocus) page.reveal(picker)
        })
    }
    Connections {
        target: page.accounting
        function onErasePassword() { approvalPassword.clear() }
        function onStateChanged() { Qt.callLater(function() { page.restorePickers() }) }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("accounting_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "accountingRefresh"
            text: page.t("refresh"); flat: true; highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            enabled: page.hasStation && !working
            onClicked: page.accounting.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("accounting_intro") }
    FormNotice {
        objectName: "accountingNotice"
        words: page.words; error: page.editorState.error; notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption { visible: !page.hasStation; text: page.t("select_station") }
    FormCaption {
        objectName: "accountingNewerWarning"
        visible: !!page.editorState.newer_revision
        text: page.t("accounting_newer_revision"); color: "#8a5c16"
    }
    FormCaption { visible: page.hasStation && !page.countingOfficer; text: page.t("accounting_read_only") }
    FormCaption { visible: !!page.editorState.historical; text: page.t("accounting_historical") }
    FormCaption { visible: page.hasStation && !page.selected.revision; text: page.t("accounting_no_record") }

    FormPanel {
        visible: page.hasStation
        implicitHeight: sources.implicitHeight + 40
        ColumnLayout {
            id: sources
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("accounting_sources") }
            FormCaption { text: page.t("accounting_source_hint") }
            FormCaption { text: page.t("accounting_special_source") }
            SourcePicker {
                id: specialPicker
                objectName: "accountingSpecialSource"
                model: page.specialOptions
                currentIndex: page.specialIndex()
                displayText: currentIndex < 0 ? page.t("accounting_choose_special") : currentText
                Accessible.name: page.t("accounting_special_source")
                onActivated: index => {
                    var row = model[index]
                    if (row) page.accounting.selectSpecial(row.id, row.revision)
                    page.restorePickers()
                }
            }
            FormCaption { text: page.t("accounting_turnout_source") }
            SourcePicker {
                id: turnoutPicker
                objectName: "accountingTurnoutSource"
                model: page.turnoutOptions
                currentIndex: page.turnoutIndex()
                Accessible.name: page.t("accounting_turnout_source")
                onActivated: index => {
                    var row = model[index]
                    if (row) page.accounting.selectTurnout(row.period, row.revision)
                    page.restorePickers()
                }
            }
            FormCaption { text: page.t("accounting_turnout_hint") }
            FormCaption { text: page.t("accounting_notes") }
            NotesArea {
                objectName: "accountingNotes"
                caption: page.t("accounting_notes")
                text: page.form.notes || ""
                onTextChanged: page.accounting.setField("notes", text)
            }
            FormCaption { visible: page.correctable; text: page.t("accounting_reason") }
            NotesArea {
                objectName: "accountingReason"
                visible: page.correctable
                caption: page.t("accounting_reason")
                text: page.form.amendment_reason || ""
                onTextChanged: page.accounting.setField("amendment_reason", text)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 700 ? 2 : 1
                columnSpacing: 12; rowSpacing: 12
                ActionButton {
                    objectName: "accountingSave"
                    visible: page.countingOfficer
                    text: page.t(page.correctable ? "accounting_correct" : "accounting_save")
                    working: page.editorState.busy
                    enabled: page.editable && !!page.form.special_paper_id
                        && (!page.correctable || !!page.form.amendment_reason.trim())
                    onClicked: page.accounting.save()
                }
                ActionButton {
                    objectName: "accountingSubmit"
                    visible: page.countingOfficer
                    text: page.t("accounting_submit")
                    working: page.editorState.busy
                    enabled: page.editable && page.selected.status === "draft"
                        && !page.editorState.dirty && !page.editorState.newer_revision && !!page.selected.source_current
                    onClicked: page.accounting.submit()
                }
            }
            FormCaption { visible: page.supervisor; text: page.t("password") }
            FormField {
                id: approvalPassword
                objectName: "accountingApprovalPassword"
                visible: page.supervisor
                echoMode: TextInput.Password
                maximumLength: 128
                working: page.editorState.busy
                enabled: page.supervisor && page.activeElection && !page.editorState.historical
                    && page.selected.status === "submitted" && !page.editorState.busy
                Accessible.name: page.t("password")
                onReveal: control => page.reveal(control)
            }
            ActionButton {
                objectName: "accountingApprove"
                visible: page.supervisor
                text: page.t("accounting_approve")
                working: page.editorState.busy
                enabled: approvalPassword.enabled && !!approvalPassword.text
                    && !page.editorState.newer_revision && !!page.selected.source_current
                onClicked: page.accounting.approve(approvalPassword.text)
            }
        }
    }

    FormPanel {
        visible: !!page.selected.revision
        implicitHeight: quantities.implicitHeight + 40
        ColumnLayout {
            id: quantities
            anchors.fill: parent; anchors.margins: 20; spacing: 16
            Heading { text: page.t("accounting_summary") }
            FormCaption {
                objectName: "accountingRevisionStatus"
                text: page.t("revision") + " " + page.exact(page.selected.revision) + " · "
                    + page.t(page.selected.status || "draft") + " · " + page.time(page.selected.event_at)
            }
            FormCaption { text: page.t("accounting_estimate_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : page.width > 600 ? 2 : 1
                columnSpacing: 24; rowSpacing: 18
                Repeater {
                    model: page.quantityKeys
                    Detail {
                        required property string modelData
                        objectName: "accounting_" + modelData
                        caption: page.t("accounting_" + modelData)
                        value: page.summary[modelData + "_display"] || "—"
                    }
                }
            }
            FormCaption { objectName: "accountingObservedHint"; text: page.t("accounting_observed_hint") }
            Heading { text: page.t("accounting_provenance") }
            Detail { caption: page.t("accounting_stock_basis"); value: page.basis(page.stock) }
            Detail { caption: page.t("accounting_special_basis"); value: page.basis(page.special) }
            Detail {
                caption: page.t("received_stock")
                value: page.references(page.special.receipt_basis, "receipt_id")
            }
            Detail {
                caption: page.t("allocation_title")
                value: page.references(page.stock.allocation_basis, "allocation_id")
            }
            Detail {
                caption: page.t("counter_return_title")
                value: page.references(page.stock.return_basis, "return_id")
            }
            Repeater {
                model: page.stock.counters || []
                Detail {
                    required property var modelData
                    caption: modelData.counter.code + " · " + modelData.counter.name
                    value: page.t("accounting_ordinary_at_desks_quantity") + " "
                        + page.exact(modelData.ordinary_remaining_quantity_display) + " · "
                        + page.t("accounting_ordinary_issued_quantity") + " "
                        + page.exact(modelData.ordinary_issued_quantity_display)
                }
            }
            Detail {
                caption: page.t("accounting_turnout_basis")
                value: page.turnoutRecord.revision ? "P(15) " + page.turnoutRecord.period_index + " · "
                    + page.t("revision") + " " + page.turnoutRecord.revision + " · "
                    + page.t(page.turnoutRecord.status) : "—"
            }
            Detail {
                objectName: "accountingTurnoutProvenance"
                visible: !!page.turnoutRecord.revision
                caption: page.t("turnout_source_mode")
                value: page.t("accounting_provenance_" + page.turnoutRecord.provenance)
            }
            Detail {
                caption: page.t("accounting_supplied_total")
                value: page.exact(page.turnoutRecord.supplied_cumulative_display)
            }
            Detail {
                caption: page.t("accounting_approved_total")
                value: page.turnoutBasis.approval_valid ? page.exact(page.turnoutRecord.derived_cumulative_end_display) : "—"
            }
            FormCaption { text: page.turnoutRecord.source_context || ""; visible: !!text }
            Detail {
                objectName: "accountingStockTurnout"
                visible: !!page.turnoutRecord.source_basis
                caption: page.t("turnout_stock_cumulative")
                value: page.exact(page.sourceBasis.stock_derived_cumulative_quantity_display)
            }
            Detail {
                objectName: "accountingOrdinaryDelta"
                visible: !!page.turnoutRecord.source_basis
                caption: page.t("turnout_ordinary_delta")
                value: page.exact(page.sourceBasis.ordinary_issued_since_activation_quantity_display)
            }
            Detail {
                visible: page.sourceBasis.recovered_cumulative_quantity_display !== undefined
                caption: page.t("turnout_recovered_cumulative")
                value: page.exact(page.sourceBasis.recovered_cumulative_quantity_display)
            }
            Detail {
                visible: page.sourceBasis.reconciliation_difference_display !== undefined
                caption: page.t("turnout_reconciliation_difference")
                value: page.exact(page.sourceBasis.reconciliation_difference_display)
            }
            Repeater {
                model: page.sourceBasis.source_events || []
                Detail {
                    required property var modelData
                    caption: page.t("fallback_kind_" + modelData.kind) + " · " + page.basis(modelData)
                    value: page.t("accounting_supplied_total") + " " + page.exact(modelData.cumulative_quantity_display)
                        + " · P(12) #" + modelData.stock_snapshot_id + " · "
                        + page.t("revision") + " " + modelData.stock_snapshot_revision
                }
            }
            Repeater {
                model: page.sourceBasis.coverage || []
                Detail {
                    required property var modelData
                    required property int index
                    objectName: "accountingCoverage" + index
                    caption: page.t("turnout_interval_" + modelData.mode) + " · "
                        + page.time(modelData.start_at) + " → " + page.time(modelData.end_at)
                    value: page.exact(modelData.cumulative_start_quantity_display) + " → "
                        + page.exact(modelData.cumulative_end_quantity_display) + " · "
                        + page.t("turnout_coverage_hourly") + " " + page.exact(modelData.hourly_quantity_display)
                }
            }
            FormCaption {
                visible: !!page.turnoutRecord.revision && !page.turnoutBasis.approval_valid
                text: page.t("accounting_unapproved_turnout"); color: "#8a5c16"
            }
            FormCaption {
                objectName: "accountingSourceStatus"
                text: page.t(page.selected.source_current ? "accounting_source_current" : "accounting_source_stale")
                color: page.selected.source_current ? "#216a50" : "#8a5c16"
            }
            FormCaption { visible: !!page.selected.approval_valid; text: page.t("accounting_approval_valid") }
            Detail { caption: page.t("accounting_notes"); value: page.selected.notes || "—" }
            Detail {
                visible: !!page.selected.amendment_reason
                caption: page.t("accounting_reason"); value: page.selected.amendment_reason || "—"
            }
        }
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: history.implicitHeight + 40
        ColumnLayout {
            id: history
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("accounting_history") }
            SourcePicker {
                id: historyPicker
                objectName: "accountingHistory"
                enabled: !page.editorState.busy && page.editorState.history.length > 0
                model: page.editorState.history.map(function(row) {
                    return {revision: row.revision,
                        label: page.t("revision") + " " + row.revision + " · " + page.t(row.status)}
                })
                currentIndex: page.historyIndex()
                Accessible.name: page.t("accounting_history")
                onActivated: index => {
                    if (model[index]) page.load(model[index].revision)
                    page.restorePickers()
                }
            }
            ActionButton {
                objectName: "accountingReload"
                text: page.t("accounting_reload")
                highlighted: false
                enabled: page.hasStation && !page.editorState.busy
                onClicked: page.load(0)
            }
        }
    }

    FormPanel {
        visible: !!page.selected.revision
        implicitHeight: reports.implicitHeight + 40
        ColumnLayout {
            id: reports
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("accounting_report") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 800 ? 3 : 1
                columnSpacing: 12; rowSpacing: 12
                ActionButton {
                    objectName: "accountingPreview"
                    text: page.t("accounting_preview")
                    enabled: !page.editorState.busy
                    onClicked: page.accounting.preview(page.locale)
                }
                ActionButton {
                    objectName: "accountingExportPdf"
                    text: page.t("export_pdf")
                    enabled: !page.editorState.busy
                    onClicked: page.exportReport("pdf")
                }
                ActionButton {
                    objectName: "accountingExportCsv"
                    text: page.t("export_csv")
                    enabled: !page.editorState.busy
                    onClicked: page.exportReport("csv")
                }
            }
            Label {
                objectName: "accountingReportPreview"
                visible: page.editorState.report.locale === page.locale
                text: page.editorState.report_text
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true; color: "#25344b"
            }
            FormCaption { text: page.editorState.export_path || ""; visible: !!text }
        }
    }

    Dialog {
        id: discardDialog
        title: page.t("accounting_discard")
        modal: true
        standardButtons: Dialog.Discard | Dialog.Cancel
        width: Math.min(520, page.width)
        onDiscarded: {
            if (page.pendingRevision) page.accounting.loadRevision(page.pendingRevision, true)
            else page.accounting.reload(true)
        }
    }
    FileDialog {
        id: exportDialog
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.accounting.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
