pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var returnsController
    required property var words
    property string locale: "tc"
    readonly property var editorState: returnsController.state
    readonly property var form: editorState.forms || ({})
    readonly property var context: editorState.context || ({})
    readonly property var election: context.election || ({})
    readonly property var station: context.station || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property bool working: editorState.busy || editorState.refreshing
    readonly property bool canCreate: !!editorState.station_id
        && editorState.role === "polling_officer"
        && (election.status === "draft" || election.status === "active")
    readonly property bool canEdit: canCreate && !editorState.historical
        && (!selected.id || (editorState.history_verified && editorState.editing))
    property string pendingAction: "new"
    property int pendingId: 0
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function counterIndex() {
        for (let index = 0; index < editorState.counters.length; index++)
            if (String(editorState.counters[index].id) === form.counter_id) return index
        return -1
    }
    function counterLabel(row) { return (row.code || "") + " · " + (row.name || "") }
    function selectedIndex() {
        for (let index = 0; index < editorState.items.length; index++)
            if (editorState.items[index].id === selected.id) return index
        return -1
    }
    function switchRecord(action, recordId, discard) {
        if (action === "new") return returnsController.newReturn(discard)
        if (action === "revision") return returnsController.loadRevision(recordId, discard)
        return returnsController.loadReturn(recordId, discard)
    }
    function openDiscardDialog(action, recordId) {
        pendingAction = action
        pendingId = recordId
        discardDialog.open()
    }
    function requestRecord(action, recordId) {
        if (working) return
        if (editorState.dirty) {
            openDiscardDialog(action, recordId)
            return
        }
        if (!switchRecord(action, recordId, false) && editorState.dirty)
            openDiscardDialog(action, recordId)
    }
    function moveFocus(control, forward) {
        let next = control.nextItemInFocusChain(forward)
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

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("counter_return_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.working
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.working
            onClicked: page.returnsController.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormNotice {
        words: page.words
        autoReveal: false
        notice: page.editorState.newer_revision ? "counter_return_newer_revision" : ""
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        implicitHeight: contextLayout.implicitHeight + 40
        ColumnLayout {
            id: contextLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.station.name || page.t("select_station") }
            FormCaption { text: page.election.name || "" }
            FormCaption { text: page.t("counter_return_hint") }
            FormCaption {
                visible: !!page.editorState.station_id && !page.canCreate
                text: page.t("counter_return_read_only")
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: pickerLayout.implicitHeight + 40
        ColumnLayout {
            id: pickerLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("counter_return_records") }
            Action {
                objectName: "counterReturnNew"
                visible: page.canCreate
                text: page.t("counter_return_new")
                highlighted: false
                working: page.working
                onClicked: page.requestRecord("new", 0)
            }
            FormCaption {
                visible: page.editorState.items.length === 0
                text: page.t("counter_return_empty")
            }
            ComboBox {
                id: recordPicker
                objectName: "counterReturnPicker"
                Layout.fillWidth: true
                model: page.editorState.items
                currentIndex: page.selectedIndex()
                enabled: !page.working
                displayText: page.selected.id ? page.t("counter_return_record") + " "
                    + page.selected.id + " · " + page.t("revision") + " "
                    + page.selected.revision : page.t("counter_return_select")
                Accessible.name: page.t("counter_return_select")
                delegate: ItemDelegate {
                    required property var modelData
                    width: recordPicker.width
                    text: page.t("counter_return_record") + " " + modelData.id + " · "
                        + page.counterLabel(modelData.counter) + " · " + modelData.series
                        + " · " + modelData.serial_from + " – " + modelData.serial_to
                    contentItem: Text {
                        text: parent.text
                        font: parent.font
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: "#25344b"
                        verticalAlignment: Text.AlignVCenter
                    }
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 24)
                }
                onActivated: index => {
                    page.requestRecord("record", model[index].id)
                    currentIndex = Qt.binding(function() { return page.selectedIndex() })
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { page.reveal(recordPicker) })
            }
            Action {
                objectName: "counterReturnEdit"
                visible: !!page.selected.id && page.canCreate && !page.editorState.historical
                    && page.editorState.history_verified && !page.editorState.editing
                text: page.t("counter_return_edit")
                working: page.working
                onClicked: page.returnsController.editSelected()
            }
            Action {
                objectName: "counterReturnReload"
                visible: !!page.selected.id
                text: page.t("reload_saved")
                highlighted: false
                working: page.working
                onClicked: page.requestRecord("record", page.selected.id)
            }
            FormCaption {
                visible: page.editorState.historical
                text: page.t("counter_return_historical")
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            FormCaption { text: page.t("allocation_counter") }
            ComboBox {
                id: counterPicker
                objectName: "counterReturnCounter"
                Layout.fillWidth: true
                enabled: page.canEdit && !page.working
                model: page.editorState.counters
                currentIndex: page.counterIndex()
                displayText: currentIndex >= 0
                    ? page.counterLabel(model[currentIndex]) : page.t("allocation_counter")
                textRole: "name"
                Accessible.name: page.t("allocation_counter")
                onActivated: index => page.returnsController.setField(
                    "counter_id", String(model[index].id))
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { page.reveal(counterPicker) })
            }
            FormCaption { text: page.t("stock_series") }
            FormField {
                objectName: "counterReturnSeries"
                text: page.form.series || ""
                readOnly: !page.canEdit
                working: page.editorState.busy
                maximumLength: 64
                Accessible.name: page.t("stock_series")
                onTextEdited: page.returnsController.setField("series", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("stock_serial_from") }
            FormField {
                objectName: "counterReturnSerialFrom"
                text: page.form.serial_from || ""
                readOnly: !page.canEdit
                working: page.editorState.busy
                maximumLength: 18
                inputMethodHints: Qt.ImhDigitsOnly
                Accessible.name: page.t("stock_serial_from")
                onTextEdited: page.returnsController.setField("serial_from", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("stock_serial_to") }
            FormField {
                objectName: "counterReturnSerialTo"
                text: page.form.serial_to || ""
                readOnly: !page.canEdit
                working: page.editorState.busy
                maximumLength: 18
                inputMethodHints: Qt.ImhDigitsOnly
                Accessible.name: page.t("stock_serial_to")
                onTextEdited: page.returnsController.setField("serial_to", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("stock_range_quantity") }
            FormField {
                objectName: "counterReturnQuantity"
                text: page.editorState.quantity_display
                readOnly: true
                Accessible.name: page.t("stock_range_quantity")
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("counter_return_event_time") }
            FormField {
                objectName: "counterReturnEventTime"
                text: page.form.event_time || ""
                placeholderText: "YYYY-MM-DD HH:mm"
                readOnly: !page.canEdit
                working: page.editorState.busy
                Accessible.name: page.t("counter_return_event_time")
                onTextEdited: page.returnsController.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption {
                visible: !!page.selected.id && (page.editorState.editing || page.editorState.dirty)
                text: page.t("amendment_reason")
            }
            TextArea {
                id: reason
                objectName: "counterReturnReason"
                visible: !!page.selected.id && (page.editorState.editing || page.editorState.dirty)
                Layout.fillWidth: true
                implicitHeight: Math.max(96, contentHeight + topPadding + bottomPadding)
                text: page.form.reason || ""
                readOnly: !page.canEdit
                enabled: !page.editorState.busy
                selectByMouse: true
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.WrapAnywhere
                topPadding: 12; bottomPadding: 12; leftPadding: 12; rightPadding: 12
                topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
                background: Rectangle { color: "white"; radius: 8; border.color: "#c4cedc" }
                Accessible.name: page.t("amendment_reason")
                onTextChanged: if (activeFocus) page.returnsController.setField("reason", text)
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(reason, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(reason, false); event.accepted = true }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { page.reveal(reason) })
            }
            Action {
                objectName: "counterReturnSave"
                visible: page.canEdit
                text: page.t("counter_return_save")
                working: page.editorState.busy
                onClicked: page.returnsController.save()
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: savedLayout.implicitHeight + 40
        ColumnLayout {
            id: savedLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("counter_return_record") + " " + (page.selected.id || "") }
            FormCaption {
                objectName: "counterReturnEventContext"
                text: page.t("counter_return_event_time") + "\n"
                    + page.returnsController.formatTime(page.selected.event_at || "")
            }
            FormCaption {
                text: page.t("entered_by") + " · " + (page.selected.actor_id || "")
                    + "\n" + page.t("server_entry") + " · "
                    + page.returnsController.formatTime(page.selected.entered_at || "")
            }
            FormCaption {
                objectName: "counterReturnReasonContext"
                text: page.t("amendment_reason") + "\n" + (page.selected.reason || "—")
            }
            Heading { text: page.t("counter_return_history") }
            Repeater {
                model: page.editorState.history
                delegate: Action {
                    required property var modelData
                    objectName: "counterReturnHistoryRevision" + modelData.revision
                    text: page.t("revision") + " " + modelData.revision + " · "
                        + page.returnsController.formatTime(modelData.event_at)
                    highlighted: page.selected.revision === modelData.revision
                    working: page.working
                    onClicked: page.requestRecord("revision", modelData.revision)
                }
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "counterReturnDiscardDialog"
        title: page.t("discard_changes")
        message: page.t("unsaved_counter_return_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.switchRecord(page.pendingAction, page.pendingId, true)
    }
}
