pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var lifecycle
    required property var words
    readonly property var editorState: lifecycle.state
    readonly property var selected: editorState.selected
    readonly property var activeElection: editorState.active_election
    readonly property bool draft: !!selected.id && !editorState.read_only
    readonly property bool selectedIsActive: !!selected.id && !!activeElection && activeElection.id === selected.id
    readonly property string liveStatus: selectedIsActive ? activeElection.status : (selected.status || "not_configured")
    readonly property bool newerSaved: selectedIsActive && (
        selected.revision !== activeElection.revision || selected.status !== activeElection.status
        || (!!activeElection.schedule && editorState.schedule.revision !== activeElection.schedule.revision)
    )
    property int pendingElectionId: 0
    signal reveal(var control)

    function t(key) { return words[key] || key }
    function selectedIndex() {
        for (var index = 0; index < editorState.elections.length; index++)
            if (editorState.elections[index].id === selected.id) return index
        return -1
    }
    function electionLabel(row) {
        return row ? row.name + " · " + t(row.status) : ""
    }
    function restorePicker() {
        electionPicker.currentIndex = Qt.binding(function() { return page.selectedIndex() })
    }
    function chooseElection(electionId) {
        if (editorState.busy) return
        if (!lifecycle.loadElection(electionId, false) && editorState.dirty) {
            pendingElectionId = electionId
            discardDialog.open()
        }
        restorePicker()
    }

    spacing: 20

    Connections {
        target: page.lifecycle
        function onStateChanged() {
            // Model refresh and activation retain the explicitly selected election.
            Qt.callLater(function() { page.restorePicker() })
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            text: page.t("election_schedule")
            textFormat: Text.PlainText
            font.pixelSize: 28
            font.weight: Font.Medium
            color: "#25344b"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh")
            highlighted: false
            flat: true
            enabled: !page.editorState.busy && !page.editorState.refreshing
            onClicked: page.lifecycle.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    FormNotice {
        objectName: "scheduleNotice"
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }

    FormPanel {
        implicitHeight: activeContent.implicitHeight + 40
        color: page.activeElection ? "#f0f7f3" : "#f5f8fc"
        border.color: page.activeElection ? "#cfe4d7" : "#e1e7f0"
        ColumnLayout {
            id: activeContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 8
            FormCaption {
                text: page.t("active_election")
                color: page.activeElection ? "#247355" : "#65758b"
            }
            Label {
                text: page.activeElection ? page.activeElection.name : page.t("no_active_election")
                textFormat: Text.PlainText
                color: "#25344b"
                font.pixelSize: page.activeElection ? 21 : 16
                font.weight: page.activeElection ? Font.Medium : Font.Normal
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            FormCaption {
                visible: !!page.activeElection
                text: page.activeElection
                    ? page.t(page.activeElection.status) + " · " + page.t("revision") + " " + page.activeElection.revision
                    : ""
            }
            FormCaption {
                visible: !!page.activeElection && !!page.activeElection.schedule
                text: page.activeElection && page.activeElection.schedule
                    ? page.t("election_date") + "  " + page.activeElection.schedule.election_date
                    : ""
            }
        }
    }

    FormPanel {
        implicitHeight: selectionContent.implicitHeight + 40
        ColumnLayout {
            id: selectionContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            FormCaption { text: page.t("selected_election") }
            ComboBox {
                id: electionPicker
                objectName: "scheduleElectionPicker"
                Layout.fillWidth: true
                model: page.editorState.elections
                textRole: "name"
                currentIndex: page.selectedIndex()
                displayText: currentIndex >= 0 && currentIndex < model.length
                    ? page.electionLabel(model[currentIndex]) : page.t("select_election")
                Accessible.name: page.t("selected_election")
                enabled: !page.editorState.busy && model.length > 0
                delegate: ItemDelegate {
                    id: electionOption
                    required property var modelData
                    required property int index
                    width: electionPicker.width
                    text: page.electionLabel(modelData)
                    highlighted: electionPicker.highlightedIndex === index
                    contentItem: Text {
                        text: electionOption.text
                        textFormat: Text.PlainText
                        color: "#25344b"
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                contentItem: Text {
                    text: electionPicker.displayText
                    textFormat: Text.PlainText
                    color: electionPicker.enabled ? "#25344b" : "#65758b"
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: electionPicker.leftPadding
                    rightPadding: electionPicker.indicator.width + electionPicker.spacing
                }
                onActivated: {
                    page.chooseElection(model[currentIndex].id)
                    page.restorePicker()
                }
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { page.reveal(electionPicker) })
            }
            FormCaption {
                visible: page.editorState.elections.length === 0
                text: page.t("no_saved_elections")
            }
            RowLayout {
                visible: !!page.selected.id
                Layout.fillWidth: true
                FormCaption {
                    text: page.selected.id
                        ? page.t(page.liveStatus) + " · " + page.t("revision") + " " + page.selected.revision
                        : ""
                }
                FormButton {
                    text: page.t("reload_saved")
                    highlighted: false
                    flat: true
                    working: page.editorState.busy
                    onClicked: page.chooseElection(page.selected.id)
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption {
                visible: page.editorState.read_only
                text: page.t("read_only_election")
            }
            FormCaption {
                visible: page.newerSaved
                text: page.t("newer_saved_version")
                color: "#8a5c16"
            }
        }
    }

    FormPanel {
        visible: !!page.selected.id
        implicitHeight: scheduleContent.implicitHeight + 48
        ColumnLayout {
            id: scheduleContent
            anchors.fill: parent
            anchors.margins: 24
            spacing: 16
            Label {
                text: page.selected.name || ""
                textFormat: Text.PlainText
                font.pixelSize: 22
                font.weight: Font.Medium
                color: "#25344b"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            FormCaption {
                text: page.editorState.schedule.revision
                    ? page.t("election_schedule") + " · " + page.t("revision") + " " + page.editorState.schedule.revision
                    : page.t("schedule_not_configured")
            }
            FormCaption { text: page.t("schedule_time_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 20
                rowSpacing: 16
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("election_date") }
                    FormField {
                        objectName: "electionDate"
                        text: page.editorState.forms.election_date
                        Accessible.name: page.t("election_date")
                        working: page.editorState.busy
                        readOnly: !page.draft
                        onTextEdited: page.lifecycle.setField("election_date", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("reporting_interval") }
                    FormField {
                        objectName: "reportingInterval"
                        text: page.editorState.forms.reporting_interval_minutes
                        Accessible.name: page.t("reporting_interval")
                        inputMethodHints: Qt.ImhDigitsOnly
                        working: page.editorState.busy
                        readOnly: !page.draft
                        onTextEdited: page.lifecycle.setField("reporting_interval_minutes", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("planned_opening") }
                    FormField {
                        objectName: "plannedOpening"
                        text: page.editorState.forms.planned_opening
                        Accessible.name: page.t("planned_opening")
                        working: page.editorState.busy
                        readOnly: !page.draft
                        onTextEdited: page.lifecycle.setField("planned_opening", text)
                        onReveal: control => page.reveal(control)
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    FormCaption { text: page.t("planned_closing") }
                    FormField {
                        objectName: "plannedClosing"
                        text: page.editorState.forms.planned_closing
                        Accessible.name: page.t("planned_closing")
                        working: page.editorState.busy
                        readOnly: !page.draft
                        onTextEdited: page.lifecycle.setField("planned_closing", text)
                        onReveal: control => page.reveal(control)
                    }
                }
            }
            FormCaption {
                visible: page.editorState.dirty && !page.editorState.read_only
                text: page.t("unsaved_schedule")
                color: "#8a5c16"
            }
            FormButton {
                objectName: "saveSchedule"
                text: page.t("save_schedule")
                Layout.fillWidth: true
                enabled: page.draft && page.editorState.dirty && !page.editorState.busy
                onClicked: page.lifecycle.save()
                onReveal: control => page.reveal(control)
            }
        }
    }

    FormPanel {
        visible: !!page.selected.id
        implicitHeight: activationContent.implicitHeight + 40
        ColumnLayout {
            id: activationContent
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Label {
                text: page.t("activate_election")
                textFormat: Text.PlainText
                font.pixelSize: 20
                font.weight: Font.Medium
                color: "#25344b"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            FormCaption { text: page.t("activation_confirmation") }
            FormButton {
                objectName: "activateElection"
                text: page.t("activate_election")
                Layout.fillWidth: true
                enabled: page.draft && !!page.editorState.schedule.revision
                    && !page.editorState.dirty && !page.editorState.busy
                onClicked: activationDialog.open()
                onReveal: control => page.reveal(control)
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.lifecycle.loadElection(page.pendingElectionId, true)
    }
    ConfirmationDialog {
        id: activationDialog
        title: page.t("activate_election")
        message: page.t("activation_confirmation") + "\n\n" + (page.selected.name || "")
        acceptLabel: page.t("activate_election")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.lifecycle.activate()
    }
}
