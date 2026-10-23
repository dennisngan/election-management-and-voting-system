pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var boxes
    required property var words
    property string locale: "tc"
    readonly property var editorState: boxes.state
    readonly property var context: editorState.context || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.forms
    readonly property var milestone: editorState.selected_milestone || ({})
    readonly property var milestoneForm: editorState.milestone_forms
    readonly property bool active: (context.election || ({})).status === "active"
    readonly property bool canCreate: active && editorState.role === "polling_officer"
    readonly property bool canDepart: canCreate && selected.origin_station_id === editorState.station_id
        && selected.mode === "send"
    readonly property bool canReceive: active && editorState.role === "counting_officer"
        && selected.destination_station_id === editorState.station_id
    readonly property bool canMilestone: active && editorState.role === "counting_officer"
        && editorState.counting_applicable
    readonly property var kinds: ["conversion_complete", "first_box_opening", "questionable_determination_start"]
    readonly property var receivedBoxes: editorState.items.filter(function(row) {
        return row.destination_station_id === page.editorState.station_id && !!row.receipt_at
    })
    property string pendingAction: "box"
    property int pendingId: 0
    property string pendingKind: ""
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function stationLabel(value, fallback) {
        return value ? value.code + " · " + value.name : String(fallback || "—")
    }
    function statusLabel(row) {
        return t(row.status === "departed" ? "box_departed_status"
            : row.status === "received" ? "box_received_status" : "box_prepared")
    }
    function boxLabel(row) {
        return row.box_reference + " · " + stationLabel(row.origin, row.origin_station_id)
            + " → " + stationLabel(row.destination, row.destination_station_id)
            + " · " + statusLabel(row) + " · " + t("revision") + " " + row.revision
    }
    function boxIndex() {
        for (var i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].id === selected.id) return i
        return -1
    }
    function milestoneBoxIndex() {
        for (var i = 0; i < receivedBoxes.length; i++)
            if (String(receivedBoxes[i].id) === milestoneForm.box_id) return i
        return -1
    }
    function chooseBox(boxId) {
        if (!boxes.loadBox(boxId, false) && editorState.dirty) {
            pendingAction = "box"; pendingId = boxId; discardDialog.open()
        }
    }
    function chooseKind(kind) {
        if (!boxes.setKind(kind, false) && editorState.dirty) {
            pendingAction = "kind"; pendingKind = kind; discardDialog.open()
        }
    }
    function reload() {
        if (!boxes.reload(false) && editorState.dirty) {
            pendingAction = "reload"; discardDialog.open()
        }
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    function exportReport(format) {
        if (!editorState.station_id || editorState.busy) return
        pendingFormat = format; pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/box-handover-"
            + editorState.station_id + "-" + locale + "." + format
        exportDialog.open()
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
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
            text: detail.value; textFormat: Text.PlainText
            color: "#25344b"; wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
        contentItem: Text {
            text: action.text; textFormat: Text.PlainText; font: action.font
            color: !action.enabled ? "#65758b" : action.highlighted ? "white" : "#1967d2"
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        onReveal: control => page.reveal(control)
    }
    component Reason: TextArea {
        id: reason
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText; wrapMode: TextEdit.WordWrap
        selectByMouse: true; clip: true; padding: 12
        enabled: !page.editorState.busy
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(reason, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(reason, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus)
            Qt.callLater(function() { if (reason.activeFocus) page.reveal(reason) })
        background: Rectangle {
            radius: 8; color: "white"
            border.color: reason.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: reason.activeFocus ? 2 : 1
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("boxes"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running; implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh"); flat: true; highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            onClicked: page.boxes.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        words: page.words; error: page.editorState.error; notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormNotice {
        words: page.words; autoReveal: false
        notice: page.editorState.newer_revision ? "box_newer_revision" : ""
    }
    FormCaption { visible: !page.editorState.station_id; text: page.t("select_station") }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: pickerLayout.implicitHeight + 40
        ColumnLayout {
            id: pickerLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("box_list") }
            ComboBox {
                id: boxPicker
                objectName: "boxPicker"
                Layout.fillWidth: true
                enabled: !page.editorState.busy
                visible: page.editorState.items.length > 0
                model: page.editorState.items
                currentIndex: page.boxIndex()
                displayText: currentIndex >= 0 ? page.boxLabel(model[currentIndex]) : page.t("box_select")
                Accessible.name: page.t("box_select")
                contentItem: Text {
                    text: boxPicker.displayText; textFormat: Text.PlainText; font: boxPicker.font
                    color: "#25344b"; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: boxDelegate
                    required property var modelData
                    required property int index
                    width: boxPicker.width
                    text: page.boxLabel(modelData)
                    highlighted: boxPicker.highlightedIndex === index
                    contentItem: Text {
                        text: boxDelegate.text; textFormat: Text.PlainText; font: boxDelegate.font
                        color: "#25344b"; wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: {
                    page.chooseBox(model[currentIndex].id)
                    currentIndex = Qt.binding(function() { return page.boxIndex() })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (boxPicker.activeFocus) page.reveal(boxPicker) })
            }
            FormCaption { visible: page.editorState.items.length === 0; text: page.t("box_none") }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "boxNew"
                    visible: page.canCreate; text: page.t("box_new")
                    working: page.editorState.busy
                    onClicked: page.chooseBox(0)
                }
                Action {
                    objectName: "boxReload"
                    text: page.t("reload_saved"); flat: true; highlighted: false
                    working: page.editorState.busy
                    onClicked: page.reload()
                }
            }
            FormCaption { visible: !page.canCreate && !page.canReceive; text: page.t("box_read_only") }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id && page.canCreate && !page.selected.id
        implicitHeight: createLayout.implicitHeight + 40
        ColumnLayout {
            id: createLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("box_new") }
            FormCaption { text: page.t("box_ref") }
            FormField {
                objectName: "boxReference"; text: page.form.box_reference
                working: page.editorState.busy; maximumLength: 64
                Accessible.name: page.t("box_ref")
                onTextEdited: page.boxes.setField("box_reference", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("box_seal") }
            FormField {
                objectName: "boxSeal"; text: page.form.seal_reference
                working: page.editorState.busy; maximumLength: 128
                Accessible.name: page.t("box_seal")
                onTextEdited: page.boxes.setField("seal_reference", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("box_prepared_time") }
            FormField {
                objectName: "boxPreparedTime"; text: page.form.prepared_time
                working: page.editorState.busy; placeholderText: "YYYY-MM-DD HH:mm"
                Accessible.name: page.t("box_prepared_time")
                onTextEdited: page.boxes.setField("prepared_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("box_time_hint") }
            Action {
                objectName: "boxCreate"
                text: page.t("box_create"); working: page.editorState.busy
                onClicked: page.boxes.create()
            }
        }
    }

    FormPanel {
        visible: !!page.selected.id
        implicitHeight: detailLayout.implicitHeight + 40
        ColumnLayout {
            id: detailLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 20
            Heading { text: page.t("box_details") + " · " + (page.selected.box_reference || "") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 780 ? 2 : 1
                columnSpacing: 28; rowSpacing: 20
                Detail { caption: page.t("box_seal"); value: page.selected.seal_reference || "" }
                Detail { caption: page.t("revision"); value: String(page.selected.revision || "") }
                Detail {
                    objectName: "boxOrigin"
                    caption: page.t("box_origin")
                    value: page.stationLabel(page.selected.origin, page.selected.origin_station_id)
                }
                Detail {
                    objectName: "boxDestination"
                    caption: page.t("box_destination")
                    value: page.stationLabel(page.selected.destination, page.selected.destination_station_id)
                }
                Detail { caption: page.t("box_status"); value: page.statusLabel(page.selected) }
                Detail { caption: page.t("box_prepared_time"); value: page.boxes.formatTime(page.selected.prepared_at || "") }
                Detail { caption: page.t("box_departure_time"); value: page.boxes.formatTime(page.selected.departure_at || "") }
                Detail { caption: page.t("box_receipt_time"); value: page.boxes.formatTime(page.selected.receipt_at || "") }
                Detail { caption: page.t("box_entered_at"); value: page.boxes.formatTime(page.selected.entered_at || "") }
                Detail { caption: page.t("box_actor"); value: String(page.selected.actor_id || "") }
            }
        }
    }

    FormPanel {
        visible: !!page.selected.id && (page.canDepart || page.canReceive)
        implicitHeight: handoverLayout.implicitHeight + 40
        ColumnLayout {
            id: handoverLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("box_handover") }
            FormCaption { text: page.t("box_event_time") }
            FormField {
                objectName: "boxEventTime"; text: page.form.event_time
                working: page.editorState.busy; placeholderText: "YYYY-MM-DD HH:mm"
                Accessible.name: page.t("box_event_time")
                onTextEdited: page.boxes.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("box_reason") }
            Reason {
                objectName: "boxEventReason"; text: page.form.reason
                Accessible.name: page.t("box_reason")
                onTextEdited: page.boxes.setField("reason", text)
            }
            Action {
                objectName: "boxDepart"
                visible: page.canDepart
                text: page.t(page.selected.departure ? "box_correct_departure" : "box_depart")
                working: page.editorState.busy
                onClicked: page.selected.departure ? page.boxes.correctDeparture() : page.boxes.depart()
            }
            Action {
                objectName: "boxReceive"
                visible: page.canReceive
                text: page.t(page.selected.receipt ? "box_correct_receipt" : "box_receive")
                working: page.editorState.busy
                onClicked: page.selected.receipt ? page.boxes.correctReceipt() : page.boxes.receive()
            }
        }
    }

    FormPanel {
        visible: !!page.selected.id
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 16
            Heading { text: page.t("box_history") }
            FormCaption { visible: page.editorState.history.length === 0; text: page.t("box_no_history") }
            Repeater {
                model: page.editorState.history
                delegate: ColumnLayout {
                    id: historyEntry
                    required property var modelData
                    Layout.fillWidth: true; spacing: 6
                    FormCaption {
                        text: page.t("revision") + " " + historyEntry.modelData.revision + " · "
                            + page.t("box_event_" + historyEntry.modelData.kind) + " · "
                            + page.boxes.formatTime(historyEntry.modelData.event_at)
                        color: "#25344b"; font.weight: Font.Medium
                    }
                    FormCaption { text: page.t("box_entered_at") + " · " + page.boxes.formatTime(historyEntry.modelData.entered_at) }
                    FormCaption { text: page.t("box_actor") + " · " + historyEntry.modelData.actor_id }
                    FormCaption { visible: !!historyEntry.modelData.reason; text: historyEntry.modelData.reason }
                }
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: milestoneLayout.implicitHeight + 40
        ColumnLayout {
            id: milestoneLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("box_milestones") }
            FormCaption { visible: !page.editorState.counting_applicable; text: page.t("box_milestones_not_applicable") }
            FormCaption {
                text: page.t("box_count_completion") + " · " + (page.editorState.count_completion
                    ? page.boxes.formatTime(page.editorState.count_completion) : page.t("box_count_unrecorded"))
            }
            FormCaption { visible: page.editorState.counting_applicable; text: page.t("box_milestone_kind") }
            ComboBox {
                id: kindPicker
                objectName: "boxMilestoneKind"
                visible: page.editorState.counting_applicable
                Layout.fillWidth: true; enabled: !page.editorState.busy
                model: page.kinds
                currentIndex: page.kinds.indexOf(page.editorState.milestone_kind)
                displayText: page.t("box_" + page.editorState.milestone_kind)
                Accessible.name: page.t("box_milestone_kind")
                delegate: ItemDelegate {
                    required property string modelData
                    required property int index
                    width: kindPicker.width; text: page.t("box_" + modelData)
                    highlighted: kindPicker.highlightedIndex === index
                }
                onActivated: {
                    page.chooseKind(model[currentIndex])
                    currentIndex = Qt.binding(function() { return page.kinds.indexOf(page.editorState.milestone_kind) })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (kindPicker.activeFocus) page.reveal(kindPicker) })
            }
            FormCaption {
                visible: page.editorState.counting_applicable
                text: page.milestone.id ? page.t("revision") + " " + page.milestone.revision
                    + " · " + page.boxes.formatTime(page.milestone.event_at) : page.t("box_no_milestones")
            }
            ColumnLayout {
                visible: page.canMilestone
                Layout.fillWidth: true; spacing: 12
                FormCaption { text: page.t("box_milestone_time") }
                FormField {
                    objectName: "boxMilestoneTime"; text: page.milestoneForm.event_time
                    working: page.editorState.busy; placeholderText: "YYYY-MM-DD HH:mm"
                    Accessible.name: page.t("box_milestone_time")
                    onTextEdited: page.boxes.setMilestoneField("event_time", text)
                    onReveal: control => page.reveal(control)
                }
                FormCaption {
                    visible: page.editorState.milestone_kind === "first_box_opening"
                    text: page.t("box_milestone_box")
                }
                ComboBox {
                    id: milestoneBoxPicker
                    objectName: "boxMilestoneBox"
                    visible: page.editorState.milestone_kind === "first_box_opening"
                    Layout.fillWidth: true; enabled: !page.editorState.busy
                    model: page.receivedBoxes; currentIndex: page.milestoneBoxIndex()
                    displayText: currentIndex >= 0 ? page.boxLabel(model[currentIndex]) : page.t("box_milestone_box")
                    Accessible.name: page.t("box_milestone_box")
                    delegate: ItemDelegate {
                        id: receivedBoxDelegate
                        required property var modelData
                        required property int index
                        width: milestoneBoxPicker.width; text: page.boxLabel(modelData)
                        highlighted: milestoneBoxPicker.highlightedIndex === index
                        contentItem: Text {
                            text: receivedBoxDelegate.text; textFormat: Text.PlainText
                            font: receivedBoxDelegate.font; color: "#25344b"
                            wrapMode: Text.WordWrap; verticalAlignment: Text.AlignVCenter
                        }
                    }
                    onActivated: page.boxes.setMilestoneField("box_id", String(model[currentIndex].id))
                    onActiveFocusChanged: if (activeFocus)
                        Qt.callLater(function() { if (milestoneBoxPicker.activeFocus) page.reveal(milestoneBoxPicker) })
                }
                FormCaption { text: page.t("box_milestone_reason") }
                Reason {
                    objectName: "boxMilestoneReason"; text: page.milestoneForm.reason
                    Accessible.name: page.t("box_milestone_reason")
                    onTextEdited: page.boxes.setMilestoneField("reason", text)
                }
                FormCaption { visible: !!page.milestone.id; text: page.t("box_milestone_correction_hint") }
                Action {
                    objectName: "boxSaveMilestone"
                    text: page.t("box_save_milestone"); working: page.editorState.busy
                    onClicked: page.boxes.saveMilestone()
                }
            }
            Heading { text: page.t("box_milestone_history") }
            FormCaption { visible: page.editorState.milestone_history.length === 0; text: page.t("box_no_milestones") }
            Repeater {
                model: page.editorState.milestone_history
                delegate: ColumnLayout {
                    id: milestoneEntry
                    required property var modelData
                    Layout.fillWidth: true; spacing: 6
                    FormCaption {
                        text: page.t("box_" + milestoneEntry.modelData.kind) + " · " + page.t("revision")
                            + " " + milestoneEntry.modelData.revision + " · " + page.boxes.formatTime(milestoneEntry.modelData.event_at)
                        color: "#25344b"; font.weight: Font.Medium
                    }
                    FormCaption { text: page.t("box_entered_at") + " · " + page.boxes.formatTime(milestoneEntry.modelData.entered_at) }
                    FormCaption { text: page.t("box_actor") + " · " + milestoneEntry.modelData.actor_id }
                    FormCaption { visible: !!milestoneEntry.modelData.reason; text: milestoneEntry.modelData.reason }
                }
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("box_report") }
            FormCaption { text: page.t("box_report_hint") }
            FormCaption { text: page.t("stock_report_language") + " · " + page.languageName(page.locale) }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 900 ? 3 : 1
                columnSpacing: 12; rowSpacing: 8
                Action {
                    objectName: "boxPreview"
                    text: page.t("stock_preview"); working: page.editorState.busy
                    onClicked: page.boxes.preview(page.locale)
                }
                Action {
                    objectName: "boxExportPdf"
                    text: page.t("stock_export_pdf"); working: page.editorState.busy
                    flat: true; highlighted: false
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "boxExportCsv"
                    text: page.t("stock_export_csv"); working: page.editorState.busy
                    flat: true; highlighted: false
                    onClicked: page.exportReport("csv")
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · " + page.languageName((page.editorState.report || ({})).locale || page.locale)
            }
            Reason {
                id: reportText
                objectName: "boxReportPreview"
                visible: !!page.editorState.report_text
                readOnly: true; text: page.editorState.report_text || ""
                Accessible.name: page.t("box_report")
            }
            FormCaption {
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes"); message: page.t("unsaved_box_changes")
        acceptLabel: page.t("discard_changes"); rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "box") page.boxes.loadBox(page.pendingId, true)
            else if (page.pendingAction === "kind") page.boxes.setKind(page.pendingKind, true)
            else page.boxes.reload(true)
        }
    }
    FileDialog {
        id: exportDialog
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.boxes.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
