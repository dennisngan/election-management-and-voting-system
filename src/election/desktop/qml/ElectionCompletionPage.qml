pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: page
    objectName: "electionCompletionPage"
    required property var completion
    required property var words
    signal reveal(var control)

    readonly property var editorState: completion ? (completion.state || ({})) : ({})
    readonly property var assessment: editorState.assessment || ({})
    readonly property var election: assessed ? assessment.election : ({})
    readonly property var blockers: assessed ? (assessment.blockers || []) : []
    readonly property bool working: !!editorState.busy || !!editorState.refreshing
    readonly property bool hasElection: Number(editorState.election_id || 0) > 0
    readonly property bool assessed: assessment.election !== undefined
        && assessment.election !== null
        && assessment.election.id === editorState.election_id
    readonly property bool ready: assessment.can_finalize === true
    readonly property string errorCode: String(editorState.error || "")
    spacing: 20

    function t(key) { return (words && words[key]) || key }
    function messageText(code) { return (words && words[code]) || t("request_failed") }
    function electionText() {
        if (!hasElection) return t("no_election")
        var name = String(election.name || "")
        var reference = "#" + String(election.id || editorState.election_id)
        return name ? name + " · " + reference : reference
    }
    function statusText() {
        if (!hasElection) return t("no_election")
        if (errorCode) return messageText(errorCode)
        if (!assessed) return t("loading")
        return t(ready ? "election_completion_ready" : "election_completion_not_ready")
    }
    function blockerText(row) {
        var text = messageText(String(row.code || ""))
        if (row.station_id !== undefined && row.station_id !== null)
            text += " · " + t("election_completion_station") + " #" + String(row.station_id)
        return text
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 28
        font.weight: Font.Medium
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    RowLayout {
        Layout.fillWidth: true
        Heading {
            objectName: "electionCompletionTitle"
            text: page.t("election_completion_title")
        }
        BusyIndicator {
            objectName: "electionCompletionBusy"
            running: page.working
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "electionCompletionRefresh"
            text: page.t("refresh")
            flat: true
            highlighted: false
            enabled: page.hasElection && !page.working
            Accessible.name: text
            onClicked: page.completion.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 4
        FormCaption { text: page.t("selected_election") }
        Label {
            objectName: "electionCompletionElection"
            text: page.electionText()
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 14
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: assessmentLayout.implicitHeight + 32
        color: "white"
        radius: 16
        border.color: "#e1e7f0"

        ColumnLayout {
            id: assessmentLayout
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            Label {
                objectName: "electionCompletionStatus"
                text: page.statusText()
                textFormat: Text.PlainText
                color: page.errorCode ? "#a13b30"
                    : !page.assessed ? "#65758b"
                    : page.ready ? "#247355" : "#805b12"
                font.pixelSize: 16
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Accessible.name: text
            }

            Repeater {
                model: page.blockers
                delegate: FormCaption {
                    id: blockerLabel
                    required property var modelData
                    required property int index
                    objectName: blockerLabel.modelData.station_id !== undefined
                        && blockerLabel.modelData.station_id !== null
                        ? "electionCompletionBlocker_" + String(blockerLabel.modelData.station_id)
                        : "electionCompletionBlocker_global_" + String(blockerLabel.index)
                    text: page.blockerText(blockerLabel.modelData)
                    color: "#805b12"
                    font.pixelSize: 14
                    Accessible.name: text
                }
            }
        }
    }
}
