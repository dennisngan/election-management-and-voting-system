pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtCore
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var snapshots
    required property var words
    property string locale: "tc"
    readonly property var editorState: snapshots.state
    readonly property var form: editorState.forms || ({})
    readonly property var context: editorState.context || ({})
    readonly property var election: context.election || ({})
    readonly property var station: context.station || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property bool canCreate: !!editorState.station_id
        && editorState.role === "polling_officer"
        && (election.status === "draft" || election.status === "active")
    readonly property bool canEdit: canCreate && !editorState.historical
        && (!selected.id || editorState.editing)
    readonly property bool working: editorState.busy || editorState.refreshing
    property string pendingAction: "new"
    property int pendingId: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function selectedIndex() {
        for (let i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].id === selected.id) return i
        return -1
    }
    function switchRecord(action, recordId, discard) {
        if (action === "new") return snapshots.newSnapshot(discard)
        if (action === "revision") return snapshots.loadRevision(recordId, discard)
        return snapshots.loadSnapshot(recordId, discard)
    }
    function requestRecord(action, recordId) {
        if (working) return
        if (!editorState.dirty && switchRecord(action, recordId, false)) return
        if (editorState.dirty) {
            pendingAction = action
            pendingId = recordId
            discardDialog.open()
        }
    }
    function moveFocus(control, forward) {
        let next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }

    function exportReport(format) {
        if (!selected.id || working) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/stock-snapshot-"
            + selected.id + "-r" + selected.revision + "-" + pendingLocale + "." + format
        exportDialog.open()
    }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, actionText.implicitHeight + 24)
        contentItem: Text {
            id: actionText
            text: action.text; font: action.font
            textFormat: Text.PlainText; wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            color: action.enabled ? (action.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component MultilineField: TextArea {
        id: field
        // The preview already rechecks focus before delayed scrolling.
        property bool revealOnlyWhileFocused: false
        Layout.fillWidth: true
        selectByMouse: true
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WrapAnywhere
        topPadding: 12; bottomPadding: 12; leftPadding: 12; rightPadding: 12
        topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (!field.revealOnlyWhileFocused || field.activeFocus) page.reveal(field)
        })
    }
    component Heading: Label {
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        property string caption
        property string value
        spacing: 6
        Layout.fillWidth: true
        FormCaption { text: parent.caption }
        Label {
            text: parent.value
            color: "#25344b"
            font.pixelSize: 24
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("snapshot_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.working
            visible: running
            implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.working
            onClicked: page.snapshots.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        objectName: "snapshotFeedback"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        implicitHeight: summary.implicitHeight + 40
        ColumnLayout {
            id: summary
            anchors.fill: parent; anchors.margins: 20
            spacing: 14
            Heading { text: page.station.name || page.t("select_station") }
            FormCaption { text: page.t("snapshot_intro") }
            FormCaption {
                objectName: "snapshotState"
                text: page.t("snapshot_" + page.editorState.snapshot_state)
                color: "#25344b"
                font.pixelSize: 16
            }
            FormCaption {
                visible: page.editorState.latest_basis_current === false
                text: page.t("snapshot_basis_stale")
                color: "#9a5b00"
            }
            FormCaption { text: page.t("snapshot_current_issued") }
            Label {
                objectName: "snapshotCurrentIssued"
                text: page.editorState.current_ordinary_issued_display
                color: "#1967d2"; font.pixelSize: 32
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            FormCaption { text: page.t("snapshot_provenance") }
        }
    }
    FormNotice {
        words: page.words
        autoReveal: false
        notice: page.editorState.newer_revision ? "stock_snapshot_newer_revision" : ""
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: recordsLayout.implicitHeight + 40
        ColumnLayout {
            id: recordsLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 12
            Heading { text: page.t("snapshot_records") }
            FormCaption {
                visible: page.editorState.items.length === 0
                text: page.t("snapshot_empty")
            }
            ComboBox {
                id: picker
                objectName: "snapshotPicker"
                Layout.fillWidth: true
                model: page.editorState.items
                currentIndex: page.selectedIndex()
                displayText: currentIndex < 0 ? page.t("snapshot_select")
                    : page.t("snapshot_record") + " " + page.selected.id + " · "
                        + page.t("revision") + " " + page.selected.revision
                enabled: !page.working
                Accessible.name: page.t("snapshot_select")
                delegate: ItemDelegate {
                    required property var modelData
                    width: picker.width
                    text: page.t("snapshot_record") + " " + modelData.id + " · "
                        + page.snapshots.formatTime(modelData.event_at) + " · "
                        + page.t("revision") + " " + modelData.revision
                    contentItem: Text {
                        text: parent.text; font: parent.font
                        textFormat: Text.PlainText; wrapMode: Text.WordWrap
                        color: "#25344b"; verticalAlignment: Text.AlignVCenter
                    }
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 24)
                }
                onActivated: page.requestRecord("record", model[currentIndex].id)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { page.reveal(picker) })
            }
            FormCaption {
                objectName: "snapshotEventContext"
                visible: !!page.selected.id
                text: page.t("snapshot_event_time") + "\n" + page.snapshots.formatTime(page.selected.event_at || "")
            }
            FormCaption {
                visible: !!page.selected.id
                text: page.t("entered_by") + " · " + (page.selected.actor_id || "—")
                    + "\n" + page.t("server_entry") + " · "
                    + page.snapshots.formatTime(page.selected.entered_at || "")
            }
            FormCaption {
                visible: !!page.selected.reason
                text: page.t("stock_reason") + "\n" + (page.selected.reason || "")
            }
            FormCaption {
                visible: page.editorState.historical
                text: page.t("snapshot_historical")
            }
            RowLayout {
                Layout.fillWidth: true
                FormButton {
                    objectName: "snapshotEdit"
                    visible: page.canCreate && !!page.selected.id
                        && !page.editorState.historical && !page.editorState.editing
                        && page.editorState.history_verified
                    text: page.t("snapshot_edit")
                    working: page.working
                    onClicked: page.snapshots.editSelected()
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "snapshotReload"
                    visible: !!page.selected.id
                    text: page.t("reload_saved")
                    highlighted: false
                    working: page.working
                    onClicked: page.requestRecord("record", page.selected.id)
                    onReveal: control => page.reveal(control)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 16
            RowLayout {
                Layout.fillWidth: true
                Heading { text: page.t("snapshot_observation") }
                FormButton {
                    objectName: "snapshotNew"
                    visible: page.canCreate
                    text: page.t("snapshot_new")
                    highlighted: false
                    working: page.working
                    onClicked: page.requestRecord("new", 0)
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption { text: page.t("snapshot_event_time") }
            FormField {
                objectName: "snapshotEventTime"
                text: page.form.event_time || ""
                readOnly: !page.canEdit
                working: page.working
                placeholderText: "YYYY-MM-DD HH:mm"
                Accessible.name: page.t("snapshot_event_time")
                onTextEdited: page.snapshots.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("snapshot_reporting_hint") }
            Repeater {
                model: page.editorState.counter_reports.length
                delegate: FormPanel {
                    id: counterCard
                    required property int index
                    readonly property var row: page.editorState.counter_reports[index] || ({})
                    readonly property var counter: row.counter || ({})
                    implicitHeight: counterLayout.implicitHeight + 32
                    color: "#f7f9fd"; radius: 12
                    ColumnLayout {
                        id: counterLayout
                        anchors.fill: parent; anchors.margins: 16
                        spacing: 12
                        Heading { text: (counterCard.counter.code || "") + " · " + (counterCard.counter.name || "") }
                        CheckBox {
                            id: reported
                            objectName: "snapshotReported" + counterCard.counter.id
                            Layout.fillWidth: true
                            checked: counterCard.row.reported === true
                            enabled: page.canEdit && !page.working
                            text: page.t("snapshot_reported")
                            onClicked: page.snapshots.setCounterReported(counterCard.counter.id, checked)
                            onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { page.reveal(reported) })
                        }
                        FormCaption {
                            objectName: "snapshotExplicitZero" + counterCard.counter.id
                            visible: counterCard.row.reported && counterCard.row.ranges.length === 0
                            text: page.t("snapshot_explicit_zero")
                        }
                        Repeater {
                            model: counterCard.row.reported ? counterCard.row.ranges.length : 0
                            delegate: ColumnLayout {
                                id: rangeRow
                                required property int index
                                readonly property var row: counterCard.row.ranges[index] || ({})
                                readonly property string suffix: counterCard.counter.id + "_" + index
                                Layout.fillWidth: true
                                spacing: 8
                                FormCaption { text: page.t("stock_series") }
                                FormField {
                                    objectName: "snapshotSeries" + rangeRow.suffix
                                    text: rangeRow.row.series || ""
                                    readOnly: !page.canEdit
                                    working: page.working
                                    Accessible.name: page.t("stock_series")
                                    onTextEdited: page.snapshots.setRangeField(counterCard.counter.id, rangeRow.index, "series", text)
                                    onReveal: control => page.reveal(control)
                                }
                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: page.width > 740 ? 3 : 1
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        FormCaption { text: page.t("stock_serial_from") }
                                        FormField {
                                            objectName: "snapshotSerialFrom" + rangeRow.suffix
                                            text: rangeRow.row.serial_from || ""
                                            readOnly: !page.canEdit
                                            working: page.working
                                            Accessible.name: page.t("stock_serial_from")
                                            onTextEdited: page.snapshots.setRangeField(counterCard.counter.id, rangeRow.index, "serial_from", text)
                                            onReveal: control => page.reveal(control)
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        FormCaption { text: page.t("stock_serial_to") }
                                        FormField {
                                            objectName: "snapshotSerialTo" + rangeRow.suffix
                                            text: rangeRow.row.serial_to || ""
                                            readOnly: !page.canEdit
                                            working: page.working
                                            Accessible.name: page.t("stock_serial_to")
                                            onTextEdited: page.snapshots.setRangeField(counterCard.counter.id, rangeRow.index, "serial_to", text)
                                            onReveal: control => page.reveal(control)
                                        }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        FormCaption { text: page.t("stock_range_quantity") }
                                        FormField {
                                            objectName: "snapshotQuantity" + rangeRow.suffix
                                            text: rangeRow.row.quantity_display || "—"
                                            readOnly: true
                                            Accessible.name: page.t("stock_range_quantity")
                                            onReveal: control => page.reveal(control)
                                        }
                                    }
                                }
                                FormButton {
                                    objectName: "snapshotRemoveRange" + rangeRow.suffix
                                    visible: page.canEdit
                                    text: page.t("stock_remove_range")
                                    highlighted: false; flat: true
                                    working: page.working
                                    onClicked: page.snapshots.removeRange(counterCard.counter.id, rangeRow.index)
                                    onReveal: control => page.reveal(control)
                                }
                            }
                        }
                        FormButton {
                            objectName: "snapshotAddRange" + counterCard.counter.id
                            visible: page.canEdit && counterCard.row.reported
                            text: page.t("snapshot_add_range")
                            highlighted: false
                            working: page.working
                            onClicked: page.snapshots.addRange(counterCard.counter.id)
                            onReveal: control => page.reveal(control)
                        }
                    }
                }
            }
            FormCaption {
                visible: !!page.selected.id && (page.editorState.editing || page.editorState.dirty)
                text: page.t("stock_reason")
            }
            MultilineField {
                id: reason
                objectName: "snapshotReason"
                visible: !!page.selected.id && (page.editorState.editing || page.editorState.dirty)
                implicitHeight: Math.max(96, contentHeight + topPadding + bottomPadding)
                text: page.form.reason || ""
                readOnly: !page.canEdit
                enabled: !page.working
                background: Rectangle { color: "white"; radius: 8; border.color: "#c4cedc" }
                Accessible.name: page.t("stock_reason")
                onTextChanged: if (activeFocus) page.snapshots.setField("reason", text)
            }
            FormButton {
                objectName: "snapshotSave"
                visible: page.canEdit
                text: page.t("snapshot_save")
                working: page.working
                onClicked: page.snapshots.save()
                onReveal: control => page.reveal(control)
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: totalsLayout.implicitHeight + 40
        ColumnLayout {
            id: totalsLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 14
            Heading { text: page.t("snapshot_saved_totals") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 740 ? 3 : 1
                Detail { caption: page.t("snapshot_allocated"); value: page.editorState.totals.ordinary_allocated_display }
                Detail { caption: page.t("snapshot_returned"); value: page.editorState.totals.ordinary_returned_display }
                Detail { caption: page.t("snapshot_net"); value: page.editorState.totals.ordinary_net_allocated_display }
            }
            FormCaption { text: page.t("snapshot_remaining") }
            Label {
                objectName: "snapshotRemainingTotal"
                text: page.editorState.totals.ordinary_remaining_display
                color: "#25344b"; font.pixelSize: 24
                textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere
                Layout.fillWidth: true
            }
            Detail { caption: page.t("snapshot_issued"); value: page.editorState.totals.ordinary_issued_display }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 12
            Heading { text: page.t("snapshot_history") }
            Repeater {
                model: page.editorState.history
                delegate: FormButton {
                    id: revisionButton
                    required property var modelData
                    objectName: "snapshotHistoryRevision" + modelData.revision
                    Layout.fillWidth: true
                    highlighted: page.selected.revision === modelData.revision
                    text: page.t("revision") + " " + modelData.revision + " · "
                        + page.snapshots.formatTime(modelData.event_at)
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 24)
                    contentItem: Text {
                        text: revisionButton.text; font: revisionButton.font
                        textFormat: Text.PlainText; wrapMode: Text.WordWrap
                        color: revisionButton.highlighted ? "white" : "#1967d2"
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    working: page.working
                    onClicked: page.requestRecord("revision", modelData.revision)
                    onReveal: control => page.reveal(control)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent; anchors.margins: 20
            spacing: 14
            Heading { text: page.t("snapshot_report") }
            FormCaption { text: page.t("snapshot_report_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 740 ? 3 : 1
                Action {
                    id: previewButton
                    objectName: "snapshotPreview"
                    text: page.t("stock_preview")
                    enabled: !!page.selected.id && !page.working
                    onClicked: page.snapshots.preview(page.locale)
                }
                Action {
                    objectName: "snapshotExportPdf"
                    text: page.t("stock_export_pdf")
                    enabled: !!page.selected.id && !page.working
                    highlighted: false
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "snapshotExportCsv"
                    text: page.t("stock_export_csv")
                    enabled: !!page.selected.id && !page.working
                    highlighted: false
                    onClicked: page.exportReport("csv")
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · "
                    + page.languageName((page.editorState.report || ({})).locale || page.locale)
            }
            MultilineField {
                id: reportText
                objectName: "snapshotReportPreview"
                visible: !!page.editorState.report_text
                implicitHeight: Math.max(120, contentHeight + topPadding + bottomPadding)
                text: page.editorState.report_text || ""
                readOnly: true
                revealOnlyWhileFocused: true
                background: Rectangle { color: "#f7f9fd"; radius: 8; border.color: "#c4cedc" }
                Accessible.name: page.t("snapshot_report")
                Keys.onEscapePressed: event => {
                    previewButton.forceActiveFocus(Qt.OtherFocusReason); event.accepted = true
                }
            }
            FormCaption {
                objectName: "snapshotExportPath"
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
                wrapMode: Text.WrapAnywhere
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "snapshotDiscardDialog"
        title: page.t("discard_changes")
        message: page.t("unsaved_stock_snapshot_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.switchRecord(page.pendingAction, page.pendingId, true)
    }
    FileDialog {
        id: exportDialog
        objectName: "snapshotExportDialog"
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.snapshots.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
