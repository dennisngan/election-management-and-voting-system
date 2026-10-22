pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var polling
    required property var words
    readonly property var editorState: polling.state
    readonly property var record: editorState.record || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var schedule: editorState.schedule || ({})
    readonly property var context: editorState.context || ({})
    readonly property var kindCodes: ["opening", "admission_closure", "queue_clear_estimate", "service_completion"]
    readonly property bool hasStation: !!editorState.station_id
    readonly property bool pollingOfficer: editorState.role === "polling_officer"
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool activeElection: !!context.election && context.election.status === "active"
    readonly property bool editable: pollingOfficer && activeElection && !editorState.busy
    readonly property bool draft: !record.revision || record.status === "draft"
    readonly property bool amendable: record.status === "submitted" || record.status === "approved"
    property string pendingKind: ""
    property bool pendingReload: false
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function time(value) { return value ? polling.formatTime(value) : t("not_recorded") }
    function kindIndex() { return kindCodes.indexOf(editorState.kind) }
    function eventCaption(kind) {
        if (kind === "opening") return t("actual_opening_at")
        if (kind === "admission_closure") return t("admission_closed_at")
        if (kind === "queue_clear_estimate") return t("queue_observed_at")
        return t("actual_service_completed_at")
    }
    function latest(kind) {
        for (var i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].kind === kind) return editorState.items[i]
        return ({})
    }
    function restoreKindPicker() {
        kindPicker.currentIndex = Qt.binding(function() { return page.kindIndex() })
    }
    function chooseKind(kind) {
        if (editorState.busy) return
        if (!polling.setKind(kind, false) && editorState.dirty) {
            pendingKind = kind
            pendingReload = false
            discardDialog.open()
        }
        restoreKindPicker()
    }
    function reloadRecord() {
        if (editorState.busy) return
        if (editorState.dirty) {
            pendingReload = true
            discardDialog.open()
        } else polling.reload(false)
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
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 15
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    Connections {
        target: page.polling
        function onErasePassword() { approvalPassword.clear() }
        function onStateChanged() {
            Qt.callLater(function() { page.restoreKindPicker() })
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading {
            text: page.t("polling_events")
            font.pixelSize: 28
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t(page.editorState.busy ? "saving" : "loading")
        }
        FormButton {
            text: page.t("refresh")
            highlighted: false
            flat: true
            working: page.editorState.busy || page.editorState.refreshing
            onClicked: page.polling.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    FormNotice {
        objectName: "pollingNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }

    FormCaption {
        visible: !page.hasStation
        text: page.t("select_station")
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: summary.implicitHeight + 40
        ColumnLayout {
            id: summary
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.t("polling_schedule_summary") }
            FormCaption { text: page.t("schedule_is_not_actual") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 16
                Detail {
                    caption: page.t("planned_opening")
                    value: page.time(page.schedule.planned_opening_at)
                }
                Detail {
                    caption: page.t("planned_closing")
                    value: page.time(page.schedule.planned_closing_at)
                }
            }
            FormCaption {
                text: page.schedule.revision
                    ? page.t("election_schedule") + " · " + page.t("revision") + " " + page.schedule.revision
                    : page.t("schedule_not_configured")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 20
                Repeater {
                    model: page.kindCodes
                    delegate: ColumnLayout {
                        id: eventSummary
                        required property string modelData
                        readonly property var saved: page.latest(modelData)
                        Layout.fillWidth: true
                        Layout.alignment: Qt.AlignTop
                        spacing: 6
                        Heading { text: page.t(eventSummary.modelData); font.pixelSize: 16 }
                        FormCaption {
                            text: eventSummary.saved.revision
                                ? page.t(eventSummary.saved.status) + " · " + page.t("revision") + " "
                                    + eventSummary.saved.revision
                                : page.t("not_recorded")
                        }
                        FormCaption {
                            text: page.eventCaption(eventSummary.modelData) + "\n"
                                + page.time(eventSummary.saved.event_at)
                        }
                        FormCaption {
                            visible: eventSummary.modelData === "queue_clear_estimate"
                            text: page.t("estimated_queue_clear_at") + "\n"
                                + page.time(eventSummary.saved.estimated_clear_at)
                        }
                    }
                }
            }
        }
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: editor.implicitHeight + 40
        ColumnLayout {
            id: editor
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            FormCaption { text: page.t("select_polling_event") }
            ComboBox {
                id: kindPicker
                objectName: "pollingKindPicker"
                Layout.fillWidth: true
                model: page.kindCodes
                currentIndex: page.kindIndex()
                displayText: page.t(page.editorState.kind)
                enabled: !page.editorState.busy
                Accessible.name: page.t("select_polling_event")
                delegate: ItemDelegate {
                    required property string modelData
                    required property int index
                    width: kindPicker.width
                    text: page.t(modelData)
                    highlighted: kindPicker.highlightedIndex === index
                }
                onActivated: page.chooseKind(model[currentIndex])
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (kindPicker.activeFocus) page.reveal(kindPicker)
                })
            }
            RowLayout {
                Layout.fillWidth: true
                FormCaption {
                    text: page.record.revision
                        ? page.t(page.record.status) + " · " + page.t("revision") + " "
                            + page.record.revision + (page.editorState.dirty ? " •" : "")
                        : page.t("not_recorded")
                }
                FormButton {
                    text: page.t("reload_saved")
                    highlighted: false
                    flat: true
                    working: page.editorState.busy
                    onClicked: page.reloadRecord()
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption {
                visible: page.editorState.newer_revision
                text: page.t("polling_newer_revision")
                color: "#8a5c16"
            }
            FormCaption {
                visible: !page.pollingOfficer
                text: page.t("polling_read_only")
            }
            FormCaption {
                visible: !page.activeElection
                text: page.t("active_election_required")
            }
            FormCaption { text: page.t("polling_time_hint") }
            FormCaption {
                visible: page.editorState.kind === "queue_clear_estimate"
                text: page.t("queue_estimate_is_forecast")
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 24
                rowSpacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.eventCaption(page.editorState.kind) }
                    FormField {
                        objectName: "pollingEventTime"
                        text: page.form.event_at || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.eventCaption(page.editorState.kind)
                        onTextEdited: page.polling.setField("event_at", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    visible: page.editorState.kind === "queue_clear_estimate"
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("estimated_queue_clear_at") }
                    FormField {
                        objectName: "pollingEstimatedClearTime"
                        text: page.form.estimated_clear_at || ""
                        readOnly: !page.editable
                        working: page.editorState.busy
                        Accessible.name: page.t("estimated_queue_clear_at")
                        onTextEdited: page.polling.setField("estimated_clear_at", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption {
                visible: page.editorState.kind === "opening"
                text: page.record.opening_status
                    ? page.t("opening_status") + " · " + page.t(page.record.opening_status)
                    : page.t("opening_status") + " · " + page.t("not_recorded")
            }
            FormCaption {
                text: page.t(page.editorState.kind === "opening" ? "opening_delay_reason" : "event_reason")
            }
            FormField {
                objectName: "pollingEventReason"
                text: page.form.reason || ""
                maximumLength: 2000
                readOnly: !page.editable
                working: page.editorState.busy
                Accessible.name: page.t(page.editorState.kind === "opening"
                    ? "opening_delay_reason" : "event_reason")
                onTextEdited: page.polling.setField("reason", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption {
                visible: page.editorState.dirty
                text: page.t("unsaved_polling_changes")
                color: "#8a5c16"
            }
            FormCaption {
                visible: page.pollingOfficer && page.amendable
                text: page.t("polling_amendment_hint")
            }
            ColumnLayout {
                visible: page.pollingOfficer && page.amendable
                Layout.fillWidth: true
                spacing: 8
                FormCaption { text: page.t("amendment_reason") }
                FormField {
                    objectName: "pollingAmendmentReason"
                    text: page.form.amendment_reason || ""
                    maximumLength: 2000
                    readOnly: !page.editable
                    working: page.editorState.busy
                    Accessible.name: page.t("amendment_reason")
                    onTextEdited: page.polling.setField("amendment_reason", text)
                    onReveal: control => page.reveal(control)
                }
            }
            Flow {
                visible: page.pollingOfficer
                Layout.fillWidth: true
                spacing: 12
                FormButton {
                    objectName: "savePollingDraft"
                    visible: page.draft
                    text: page.t("save_polling_draft")
                    enabled: page.editable && page.draft && !!page.schedule.revision
                        && (!page.record.revision || page.editorState.dirty)
                    onClicked: page.polling.save()
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "submitPolling"
                    visible: page.draft
                    text: page.t("submit_polling")
                    enabled: page.editable && page.record.status === "draft"
                        && !page.editorState.dirty && !page.editorState.newer_revision
                    onClicked: page.polling.submit()
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "amendPolling"
                    visible: page.amendable
                    text: page.t("amend_polling")
                    enabled: page.editable && page.amendable && !!(page.form.amendment_reason || "").trim()
                        && !page.editorState.newer_revision
                    onClicked: page.polling.amend()
                    onReveal: control => page.reveal(control)
                }
            }
        }
    }

    FormPanel {
        visible: page.hasStation && page.supervisor
        implicitHeight: approval.implicitHeight + 40
        ColumnLayout {
            id: approval
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("approve_polling") }
            FormCaption { text: page.t("polling_approval_hint") }
            FormCaption {
                text: page.record.revision
                    ? page.t(page.editorState.kind) + " · " + page.t("revision") + " " + page.record.revision
                    : page.t("not_recorded")
            }
            FormCaption { text: page.t("approval_password") }
            FormField {
                id: approvalPassword
                objectName: "pollingApprovalPassword"
                echoMode: TextInput.Password
                maximumLength: 128
                working: page.editorState.busy
                Accessible.name: page.t("approval_password")
                onReveal: control => page.reveal(control)
            }
            FormButton {
                objectName: "approvePolling"
                text: page.t("approve_polling")
                enabled: page.activeElection && page.record.status === "submitted"
                    && !page.editorState.busy && !page.editorState.dirty
                    && !page.editorState.newer_revision && approvalPassword.text.length > 0
                onClicked: page.polling.approve(approvalPassword.text)
                onReveal: control => page.reveal(control)
            }
        }
    }

    FormPanel {
        visible: page.hasStation
        implicitHeight: history.implicitHeight + 40
        ColumnLayout {
            id: history
            anchors.fill: parent
            anchors.margins: 20
            spacing: 20
            Heading { text: page.t("polling_history") }
            FormCaption {
                visible: page.editorState.history.length === 0
                text: page.t(page.editorState.busy || page.editorState.refreshing ? "loading" : "no_polling_history")
            }
            Repeater {
                model: page.editorState.history
                delegate: ColumnLayout {
                    id: entry
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 10
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
                    Heading {
                        text: page.t("revision") + " " + entry.modelData.revision + " · "
                            + page.t(entry.modelData.status)
                        font.pixelSize: 16
                    }
                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width > 780 ? 2 : 1
                        columnSpacing: 24
                        rowSpacing: 14
                        Detail {
                            caption: page.eventCaption(entry.modelData.kind)
                            value: page.time(entry.modelData.event_at)
                        }
                        Detail {
                            visible: entry.modelData.kind === "queue_clear_estimate"
                            caption: page.t("estimated_queue_clear_at")
                            value: page.time(entry.modelData.estimated_clear_at)
                        }
                        Detail {
                            caption: page.t("server_entry")
                            value: page.time(entry.modelData.entered_at) + "\n"
                                + page.t("entered_by") + " " + entry.modelData.actor_id
                        }
                        Detail {
                            caption: page.t("submission")
                            value: entry.modelData.submitted_at
                                ? page.time(entry.modelData.submitted_at) + "\n"
                                    + page.t("submitted_by") + " " + entry.modelData.submitted_by
                                : page.t("not_recorded")
                        }
                        Detail {
                            caption: page.t("approval")
                            value: entry.modelData.approved_at
                                ? page.time(entry.modelData.approved_at) + "\n"
                                    + page.t("approved_by") + " " + entry.modelData.approved_by
                                : page.t("not_recorded")
                        }
                        Detail {
                            caption: page.t("planned_time_basis")
                            value: page.time(entry.modelData.planned_at) + "\n"
                                + page.t("election_schedule") + " · " + page.t("revision") + " "
                                + entry.modelData.schedule_revision
                        }
                    }
                    Detail {
                        visible: !!entry.modelData.opening_status
                        caption: page.t("opening_status")
                        value: entry.modelData.opening_status ? page.t(entry.modelData.opening_status) : ""
                    }
                    Detail {
                        caption: page.t(entry.modelData.kind === "opening" ? "opening_delay_reason" : "event_reason")
                        value: entry.modelData.reason || page.t("not_recorded")
                    }
                    Detail {
                        caption: page.t("amendment_reason")
                        value: entry.modelData.amendment_reason || page.t("not_recorded")
                    }
                }
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_polling_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingReload) page.polling.reload(true)
            else page.polling.setKind(page.pendingKind, true)
            page.restoreKindPicker()
        }
    }
}
