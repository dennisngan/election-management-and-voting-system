pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var fallback
    required property var words
    readonly property var editorState: fallback.state
    readonly property var form: editorState.forms || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property var snapshot: selected.stock_snapshot_display || ({})
    readonly property bool recovery: form.kind === "recovery"
    readonly property var election: (editorState.context || ({})).election || ({})
    readonly property bool working: editorState.busy || editorState.refreshing
    readonly property bool officer: editorState.role === "polling_officer"
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool editable: officer && election.status === "active"
        && (!selected.id || editorState.editing) && !editorState.historical
    readonly property bool canSubmit: officer && selected.status === "draft"
        && !editorState.historical && election.status === "active"
    readonly property bool canApprove: supervisor && selected.status === "submitted"
        && !editorState.historical && election.status === "active"
    readonly property bool canAmend: officer && election.status === "active"
        && !editorState.historical && !editorState.editing
        && ["submitted", "approved"].indexOf(selected.status) >= 0
    property string pendingAction: "reload"
    property int pendingIdentity: 0
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function amount(value) { return value === undefined || value === null ? "—" : String(value) }
    function time(value) { return fallback.formatTime(value || "") }
    function recordLabel(record) {
        return t("fallback_kind_" + record.kind) + " " + record.id + " · "
            + t("revision") + " " + record.revision + " · " + t("fallback_status_" + record.status)
    }
    function comparisonValue(key) {
        let display = selected.reconciliation_display || ({})
        return display[key] !== undefined ? display[key] : "—"
    }
    function switchSelection(action, identity, discard) {
        if (action === "activation" || action === "recovery")
            return fallback.newRecord(action, discard)
        if (action === "record") return fallback.selectRecord(identity, discard)
        if (action === "revision") return fallback.loadRevision(identity, discard)
        return fallback.reload(discard)
    }
    function requestSelection(action, identity) {
        if (working) return
        if (editorState.dirty) {
            pendingAction = action; pendingIdentity = identity; discardDialog.open()
        } else switchSelection(action, identity, false)
    }

    Connections {
        target: page.fallback
        function onErasePassword() { approvalPassword.text = "" }
    }

    component Heading: Label {
        Layout.fillWidth: true
        color: "#25344b"; font.pixelSize: 20; font.weight: Font.Medium
        textFormat: Text.PlainText; wrapMode: Text.WordWrap
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, contentItem.implicitHeight + 24)
        contentItem: Text {
            text: action.text; font: action.font
            color: !action.enabled ? "#8a96a8" : action.highlighted ? "white" : "#1967d2"
            textFormat: Text.PlainText; wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        onReveal: control => page.reveal(control)
    }

    component MultilineField: TextArea {
        id: field
        Layout.fillWidth: true
        readOnly: !page.editable; enabled: !page.working
        selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.WrapAnywhere
        topPadding: 12; bottomPadding: 12; leftPadding: 12; rightPadding: 12
        topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
        implicitHeight: Math.max(96, contentHeight + topPadding + bottomPadding)
        background: Rectangle { color: "white"; radius: 8; border.color: "#c4cedc" }
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => {
            let next = field.nextItemInFocusChain(true)
            if (next) next.forceActiveFocus(Qt.TabFocusReason)
            event.accepted = true
        }
        Keys.onBacktabPressed: event => {
            let next = field.nextItemInFocusChain(false)
            if (next) next.forceActiveFocus(Qt.BacktabFocusReason)
            event.accepted = true
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("fallback_title"); font.pixelSize: 28 }
        BusyIndicator { running: page.working; visible: running }
        FormButton {
            objectName: "fallbackRefresh"; text: page.t("refresh")
            highlighted: false; working: page.working
            onClicked: page.fallback.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        words: page.words; error: page.editorState.error; notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: modeLayout.implicitHeight + 40
        ColumnLayout {
            id: modeLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            Heading {
                objectName: "fallbackMode"
                text: page.t(page.editorState.mode === "fallback"
                    ? "fallback_mode_stock" : "fallback_mode_normal")
                color: "#1967d2"
            }
            FormCaption { text: page.t("fallback_intro") }
        }
    }
    FormNotice {
        words: page.words; autoReveal: false
        notice: page.editorState.newer_revision ? "fallback_newer_revision" : ""
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: recordsLayout.implicitHeight + 40
        ColumnLayout {
            id: recordsLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("fallback_records") }
            FormCaption {
                visible: page.editorState.items.length === 0
                text: page.t("fallback_empty")
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 2 : 1
                visible: page.officer && page.election.status === "active"
                Action {
                    objectName: "fallbackNewActivation"; text: page.t("fallback_new_activation")
                    highlighted: false; working: page.working
                    onClicked: page.requestSelection("activation", 0)
                }
                Action {
                    objectName: "fallbackNewRecovery"; text: page.t("fallback_new_recovery")
                    working: page.working
                    enabled: !page.working && page.editorState.active_activation_id !== null
                    onClicked: page.requestSelection("recovery", 0)
                }
            }
            ComboBox {
                id: recordPicker
                objectName: "fallbackRecordPicker"
                Layout.fillWidth: true; enabled: !page.working && model.length > 0
                model: page.editorState.items
                currentIndex: model.findIndex(row => row.id === page.selected.id)
                displayText: page.selected.id ? page.recordLabel(page.selected)
                    : page.t("fallback_choose_record")
                Accessible.name: page.t("fallback_choose_record")
                delegate: ItemDelegate {
                    required property var modelData
                    width: recordPicker.width; text: page.recordLabel(modelData)
                }
                onActivated: if (currentIndex >= 0)
                    page.requestSelection("record", model[currentIndex].id)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (recordPicker.activeFocus) page.reveal(recordPicker)
                })
            }
            Action {
                objectName: "fallbackBeginAmend"; visible: page.canAmend
                text: page.t("fallback_begin_amend"); highlighted: false; working: page.working
                enabled: !page.working && !page.editorState.newer_revision
                onClicked: page.fallback.beginAmend()
            }
            Action {
                objectName: "fallbackReload"; text: page.t("reload_saved")
                highlighted: false; working: page.working
                onClicked: page.requestSelection("reload", 0)
            }
            FormCaption {
                objectName: "fallbackRecordContext"; visible: !!page.selected.id
                text: page.selected.id ? page.recordLabel(page.selected) + "\n"
                    + page.t("server_entry") + " · " + page.time(page.selected.entered_at)
                    + "\n" + page.t("entered_by") + " · " + page.amount(page.selected.actor_id) : ""
            }
            FormCaption { visible: page.editorState.historical; text: page.t("fallback_historical") }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading {
                objectName: "fallbackFormTitle"
                text: page.t(page.editorState.editing ? "fallback_correction"
                    : page.recovery ? "fallback_recovery" : "fallback_activation")
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 2 : 1
                visible: page.recovery
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_parent_activation_id") }
                    FormField {
                        objectName: "fallbackActivationId"
                        text: page.form.activation_id || ""; readOnly: true; working: page.working
                        Accessible.name: page.t("fallback_parent_activation_id")
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_parent_activation_revision") }
                    FormField {
                        objectName: "fallbackActivationRevision"
                        text: page.form.activation_revision || ""; readOnly: true
                        working: page.working
                        Accessible.name: page.t("fallback_parent_activation_revision")
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption { text: page.t("fallback_event_time") }
            FormField {
                objectName: "fallbackEventTime"
                text: page.form.event_time || ""; readOnly: !page.editable; working: page.working
                Accessible.name: page.t("fallback_event_time")
                onTextEdited: page.fallback.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("fallback_cumulative") }
            FormField {
                objectName: "fallbackCumulative"
                text: page.form.cumulative_quantity || ""; readOnly: !page.editable
                working: page.working; maximumLength: 19
                validator: RegularExpressionValidator { regularExpression: /[0-9]{0,19}/ }
                Accessible.name: page.t("fallback_cumulative")
                onTextEdited: page.fallback.setField("cumulative_quantity", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("fallback_snapshot_hint") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 2 : 1
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_snapshot_id") }
                    FormField {
                        objectName: "fallbackSnapshotId"
                        text: page.form.stock_snapshot_id || ""; readOnly: !page.editable
                        working: page.working; maximumLength: 19
                        validator: RegularExpressionValidator { regularExpression: /[0-9]{0,19}/ }
                        Accessible.name: page.t("fallback_snapshot_id")
                        onTextEdited: page.fallback.setField("stock_snapshot_id", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_snapshot_revision") }
                    FormField {
                        objectName: "fallbackSnapshotRevision"
                        text: page.form.stock_snapshot_revision || ""; readOnly: !page.editable
                        working: page.working; maximumLength: 19
                        validator: RegularExpressionValidator { regularExpression: /[0-9]{0,19}/ }
                        Accessible.name: page.t("fallback_snapshot_revision")
                        onTextEdited: page.fallback.setField("stock_snapshot_revision", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption { text: page.t("fallback_source") }
            MultilineField {
                objectName: "fallbackSource"
                text: page.form.source_context || ""
                Accessible.name: page.t("fallback_source")
                onTextChanged: if (activeFocus) page.fallback.setField("source_context", text)
            }
            FormCaption {
                visible: page.recovery || page.editorState.editing || !!page.form.reason
                text: page.t("fallback_reason")
            }
            MultilineField {
                objectName: "fallbackReason"
                visible: page.recovery || page.editorState.editing || !!page.form.reason
                text: page.form.reason || ""
                Accessible.name: page.t("fallback_reason")
                onTextChanged: if (activeFocus) page.fallback.setField("reason", text)
            }
            Action {
                objectName: "fallbackSave"; visible: page.editable && !page.selected.id
                text: page.t(page.recovery ? "fallback_save_recovery" : "fallback_save")
                working: page.working
                onClicked: page.fallback.save()
            }
            Action {
                objectName: "fallbackAmend"
                visible: page.editable && !!page.selected.id && page.editorState.editing
                text: page.t("fallback_amend_save"); working: page.working
                enabled: !page.working && !page.editorState.newer_revision
                onClicked: page.fallback.amend()
            }
            Action {
                objectName: "fallbackSubmit"; visible: page.canSubmit
                text: page.t("fallback_submit"); working: page.working
                enabled: !page.working && !page.editorState.dirty && !page.editorState.newer_revision
                onClicked: page.fallback.submit()
            }
        }
    }
    FormPanel {
        visible: page.selected.kind === "recovery" && page.selected.reconciliation !== undefined
        implicitHeight: comparisonLayout.implicitHeight + 40
        ColumnLayout {
            id: comparisonLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading {
                objectName: "fallbackReconciliationTitle"
                text: page.t("fallback_reconciliation")
            }
            FormCaption { text: page.t("fallback_reconciliation_hint") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 3 : 1
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_stock_cumulative") }
                    Label {
                        objectName: "fallbackComparisonStock"
                        Layout.fillWidth: true; textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere; font.pixelSize: 24; color: "#25344b"
                        text: page.comparisonValue("stock_derived_cumulative_quantity")
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_recovered_cumulative") }
                    Label {
                        objectName: "fallbackComparisonRecovered"
                        Layout.fillWidth: true; textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere; font.pixelSize: 24; color: "#25344b"
                        text: page.comparisonValue("recovered_cumulative_quantity")
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_reconciliation_difference") }
                    Label {
                        objectName: "fallbackComparisonDifference"
                        Layout.fillWidth: true; textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere; font.pixelSize: 24; color: "#25344b"
                        text: page.comparisonValue("difference")
                    }
                }
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: sourceLayout.implicitHeight + 40
        ColumnLayout {
            id: sourceLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("fallback_frozen_source") }
            FormCaption {
                objectName: "fallbackSnapshotReference"
                text: page.amount(page.selected.stock_snapshot_id) + " · "
                    + page.t("revision") + " " + page.amount(page.selected.stock_snapshot_revision)
                    + " · " + page.time(page.snapshot.event_at)
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 2 : 1
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_remaining") }
                    Label {
                        objectName: "fallbackOrdinaryRemaining"
                        Layout.fillWidth: true; textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere; font.pixelSize: 24; color: "#25344b"
                        text: page.snapshot.ordinary_remaining_quantity_display || "—"
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    FormCaption { text: page.t("fallback_ordinary_issued") }
                    Label {
                        objectName: "fallbackOrdinaryIssued"
                        Layout.fillWidth: true; textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere; font.pixelSize: 24; color: "#25344b"
                        text: page.snapshot.ordinary_issued_quantity_display || "—"
                    }
                }
            }
            Repeater {
                model: page.snapshot.counters || []
                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true; spacing: 8
                    FormCaption {
                        text: page.t("fallback_counter") + " · "
                            + (parent.modelData.counter.name || parent.modelData.counter.id)
                    }
                    Label {
                        objectName: "fallbackCounterRemaining" + parent.modelData.counter.id
                        Layout.fillWidth: true; font.pixelSize: 18; color: "#25344b"
                        textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                        text: parent.modelData.ordinary_remaining_quantity_display || "—"
                    }
                    Repeater {
                        model: parent.modelData.ranges
                        delegate: FormCaption {
                            required property var modelData
                            text: modelData.series + " · " + modelData.serial_from + "–"
                                + modelData.serial_to + " · " + (modelData.quantity_display || "—")
                        }
                    }
                }
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id && page.editorState.history.length > 0
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("fallback_history") }
            Repeater {
                model: page.editorState.history
                delegate: Action {
                    required property var modelData
                    objectName: "fallbackHistoryRevision" + modelData.revision
                    text: page.recordLabel(modelData) + " · " + page.time(modelData.event_at)
                    highlighted: page.selected.revision === modelData.revision
                    working: page.working
                    onClicked: page.requestSelection("revision", modelData.revision)
                }
            }
        }
    }
    FormPanel {
        visible: page.canApprove
        implicitHeight: approvalLayout.implicitHeight + 40
        ColumnLayout {
            id: approvalLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("fallback_approval") }
            FormCaption { text: page.t("fallback_approval_hint") }
            FormField {
                id: approvalPassword
                objectName: "fallbackApprovalPassword"
                text: ""; echoMode: TextInput.Password; working: page.working
                Accessible.name: page.t("fallback_approval_password")
                onReveal: control => page.reveal(control)
                onAccepted: page.fallback.approve(text)
            }
            Action {
                objectName: "fallbackApprove"; visible: page.canApprove
                text: page.t(page.recovery ? "fallback_approve_recovery" : "fallback_approve")
                working: page.working
                enabled: !page.working && !page.editorState.newer_revision
                onClicked: page.fallback.approve(approvalPassword.text)
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "fallbackDiscardDialog"
        title: page.t("discard_changes"); message: page.t("unsaved_fallback_changes")
        acceptLabel: page.t("discard_changes"); rejectLabel: page.t("keep_editing")
        onConfirmed: page.switchSelection(page.pendingAction, page.pendingIdentity, true)
    }
}
