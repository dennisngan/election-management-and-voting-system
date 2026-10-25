pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var serverBackups
    required property var words
    property string locale: "tc"
    signal reveal(var control)

    readonly property var editorState: serverBackups.state || ({})
    readonly property var jobs: editorState.jobs || []
    readonly property bool administrator: editorState.role === "administrator"
    readonly property bool working: !!editorState.busy || !!editorState.refreshing
    spacing: 20

    function t(key) { return words[key] || key }
    function statusText(status) {
        if (status === "succeeded") return t("server_backup_status_succeeded")
        if (status === "failed") return t("server_backup_status_failed")
        return t("server_backup_status_running")
    }
    function sizeText(row) {
        if (row.size_bytes_display !== undefined) return row.size_bytes_display
        return row.size_bytes === null || row.size_bytes === undefined
            ? t("server_backup_not_recorded") : String(row.size_bytes)
    }
    function timeText(value) {
        return value === null || value === undefined || value === ""
            ? t("server_backup_not_recorded") : String(value)
    }

    component Heading: Label {
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Caption: Label {
        color: "#65758b"
        font.pixelSize: 13
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        property string label
        property string value
        property string valueObjectName: ""
        spacing: 4
        Layout.fillWidth: true
        Caption { text: parent.label }
        Label {
            objectName: parent.valueObjectName
            text: parent.value
            color: "#25344b"
            font.pixelSize: 14
            font.family: parent.valueObjectName.indexOf("Sha256") >= 0
                ? (Qt.platform.os === "windows" ? "Consolas" : "Menlo") : ""
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, actionLabel.implicitHeight + 24)
        contentItem: Text {
            id: actionLabel
            text: action.text
            color: action.enabled ? "white" : "#8a96a8"
            font: action.font
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        onReveal: control => page.reveal(control)
    }

    RowLayout {
        Layout.fillWidth: true
        Heading {
            objectName: "serverBackupsTitle"
            text: page.t("server_backups_title")
            font.pixelSize: 28
        }
        BusyIndicator {
            objectName: "serverBackupsBusy"
            running: page.working
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "serverBackupRefresh"
            text: page.t("server_backups_refresh")
            flat: true
            highlighted: false
            enabled: page.administrator && !page.working
            Accessible.name: text
            onClicked: page.serverBackups.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    Caption {
        objectName: "serverBackupsIntro"
        text: page.t("server_backups_intro")
        font.pixelSize: 14
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: requestLayout.implicitHeight + 40
        color: "white"
        radius: 16
        border.color: "#e1e7f0"
        ColumnLayout {
            id: requestLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading {
                text: page.t("server_backup_create_section")
            }
            Caption {
                text: page.t("server_backup_create_hint")
            }
            Caption {
                objectName: "serverBackupPrivacyHint"
                text: page.t("server_backup_privacy_hint")
                color: "#53657b"
            }
            Action {
                objectName: "serverBackupCreate"
                text: page.t(page.editorState.busy
                    ? "server_backup_creating" : "server_backup_create")
                enabled: page.administrator && !page.working
                    && !page.editorState.pending_request_id
                visible: page.administrator
                Accessible.name: text
                onClicked: page.serverBackups.requestBackup()
            }
        }
    }

    Rectangle {
        objectName: "serverBackupUncertain"
        Layout.fillWidth: true
        visible: page.administrator
            && (!!page.editorState.uncertain_save
                || (!!page.editorState.pending_request_id && !page.editorState.busy))
        implicitHeight: uncertaintyLayout.implicitHeight + 32
        color: "#fff8e1"
        radius: 12
        border.color: "#e8d89e"
        ColumnLayout {
            id: uncertaintyLayout
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10
            Heading {
                text: page.t(page.editorState.uncertain_save
                    ? "server_backup_outcome_uncertain" : "server_backup_pending")
            }
            Caption {
                text: page.t(page.editorState.uncertain_save
                    ? "server_backup_uncertain_hint" : "server_backup_running_unconfirmed")
            }
            Caption {
                visible: !!page.editorState.pending_request_id
                text: page.t("server_backup_request_id") + " · "
                    + String(page.editorState.pending_request_id || "")
                wrapMode: Text.WrapAnywhere
            }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "serverBackupCheckOutcome"
                    text: page.t("server_backup_check_outcome")
                    visible: !!page.editorState.pending_request_id
                    enabled: page.administrator && !page.working
                    onClicked: page.serverBackups.checkPendingOutcome()
                }
                Action {
                    objectName: "serverBackupRetryRequest"
                    text: page.t("server_backup_retry_request")
                    visible: !!page.editorState.uncertain_save
                        && !!page.editorState.pending_request_id
                    enabled: page.administrator && !page.working
                    onClicked: page.serverBackups.requestBackup()
                }
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: statusLayout.implicitHeight + 32
        visible: !!page.editorState.error || !!page.editorState.notice
        color: page.editorState.error ? "#fce8e6" : "#e7f3ed"
        radius: 12
        ColumnLayout {
            id: statusLayout
            anchors.fill: parent
            anchors.margins: 16
            Caption {
                objectName: "serverBackupStatusMessage"
                color: page.editorState.error ? "#a13b30" : "#247355"
                text: page.t(page.editorState.error || page.editorState.notice)
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: historyLayout.implicitHeight + 40
        color: "white"
        radius: 16
        border.color: "#e1e7f0"
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading {
                text: page.t("server_backup_history")
            }
            Caption {
                objectName: "serverBackupEmpty"
                visible: page.jobs.length === 0
                text: page.t("server_backup_empty")
            }
            Repeater {
                model: page.jobs
                delegate: Rectangle {
                    id: jobCard
                    required property var modelData
                    required property int index
                    readonly property bool latest: index === 0
                    Layout.fillWidth: true
                    implicitHeight: jobLayout.implicitHeight + 32
                    color: "#f8fafd"
                    radius: 12
                    border.color: "#e1e7f0"

                    ColumnLayout {
                        id: jobLayout
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            Heading {
                                text: page.t("server_backup_id") + " · " + jobCard.modelData.id
                                font.pixelSize: 16
                            }
                            Rectangle {
                                radius: 12
                                color: jobCard.modelData.status === "succeeded" ? "#e7f3ed"
                                    : jobCard.modelData.status === "failed" ? "#fce8e6" : "#fff4d6"
                                implicitWidth: backupStatus.implicitWidth + 20
                                implicitHeight: backupStatus.implicitHeight + 10
                                Label {
                                    id: backupStatus
                                    objectName: jobCard.latest ? "serverBackupStatus"
                                        : "serverBackupStatus_" + jobCard.modelData.id
                                    anchors.centerIn: parent
                                    text: page.statusText(jobCard.modelData.status)
                                    color: jobCard.modelData.status === "succeeded" ? "#247355"
                                        : jobCard.modelData.status === "failed" ? "#a13b30" : "#805b12"
                                    font.pixelSize: 12
                                    textFormat: Text.PlainText
                                    Accessible.name: text
                                }
                            }
                        }
                        GridLayout {
                            Layout.fillWidth: true
                            columns: width < 640 ? 1 : 2
                            columnSpacing: 24
                            rowSpacing: 12
                            Detail {
                                label: page.t("server_backup_request_id")
                                value: String(jobCard.modelData.request_id)
                                valueObjectName: jobCard.latest ? "serverBackupLatestRequestId" : ""
                            }
                            Detail {
                                label: page.t("server_backup_requested_at")
                                value: page.timeText(jobCard.modelData.requested_at)
                            }
                            Detail {
                                label: page.t("server_backup_completed_at")
                                value: page.timeText(jobCard.modelData.completed_at)
                            }
                            Detail {
                                label: page.t("server_backup_cutoff_start")
                                value: page.timeText(jobCard.modelData.cutoff_start)
                            }
                            Detail {
                                label: page.t("server_backup_cutoff_end")
                                value: page.timeText(jobCard.modelData.cutoff_end)
                            }
                            Detail {
                                label: page.t("server_backup_size_bytes")
                                value: page.sizeText(jobCard.modelData)
                                valueObjectName: jobCard.latest ? "serverBackupLatestSize" : ""
                            }
                            Detail {
                                label: page.t("server_backup_sha256")
                                value: page.timeText(jobCard.modelData.sha256)
                                valueObjectName: jobCard.latest ? "serverBackupLatestSha256" : ""
                            }
                            Detail {
                                label: page.t("server_backup_error_code")
                                value: page.timeText(jobCard.modelData.error_code)
                                visible: jobCard.modelData.error_code !== null
                                    && jobCard.modelData.error_code !== undefined
                            }
                        }
                    }
                }
            }
        }
    }
}
