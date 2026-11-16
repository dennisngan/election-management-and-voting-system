pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var periods
    required property var words
    property string locale: "tc"
    readonly property var editorState: periods.state
    readonly property var selected: editorState.selected || ({})
    readonly property var current: editorState.current || ({})
    readonly property var reviewedPeriod: editorState.selected_period_context || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var context: editorState.context || ({})
    readonly property var schedule: editorState.schedule || ({})
    readonly property var summary: editorState.summary || ({})
    readonly property bool hasStation: !!editorState.station_id
    readonly property bool hasReviewedPeriod: !!reviewedPeriod.period_index
        && reviewedPeriod.period_index === editorState.selected_period
    readonly property bool pollingOfficer: editorState.role === "polling_officer"
    readonly property bool supervisor: editorState.role === "supervisor"
    readonly property bool activeElection: !!context.election && context.election.status === "active"
    readonly property bool editable: pollingOfficer && activeElection && hasReviewedPeriod
        && !editorState.busy && !editorState.historical
    readonly property bool draft: !selected.revision || selected.status === "draft"
    readonly property bool amendable: selected.status === "submitted" || selected.status === "approved"
    readonly property bool canApprove: supervisor && activeElection && hasReviewedPeriod
        && selected.status === "submitted" && !editorState.busy && !editorState.dirty
        && !editorState.historical && !editorState.newer_revision && !!current.basis_current
    property string pendingAction: "reload"
    property var pendingValue: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    property bool pendingStationReport: false
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function time(value) { return value ? periods.formatTime(value) : "—" }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    function categoryLabel(row, member) {
        return row[(member ? "category_label_" : "label_") + locale] || "—"
    }
    function previewReport() {
        if (reportScope.currentIndex === 1) periods.previewStation(locale)
        else periods.preview(locale)
    }
    function exportReport(format) {
        if (!hasStation || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        pendingStationReport = reportScope.currentIndex === 1
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        var basis = pendingStationReport ? "station-current"
            : "period-" + selected.period_index_display + "-revision-" + selected.revision
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/complaint-period-"
            + editorState.station_id + "-" + basis + "-" + locale + "." + format
        exportDialog.open()
    }
    function selectedIndex() {
        for (let i = 0; i < editorState.items.length; i++)
            if (editorState.items[i].period_index === editorState.selected_period) return i
        return -1
    }
    function periodLabel(row) {
        return t("complaint_period_period") + " " + row.period_index_display + " · "
            + time(row.start_at) + " → " + time(row.end_at) + " · " + t(row.status)
    }
    function restorePicker() {
        periodPicker.currentIndex = Qt.binding(function() { return page.selectedIndex() })
    }
    function choose(action, value) {
        if (editorState.busy) return
        var accepted = false
        if (action === "period") accepted = periods.selectPeriod(value, false)
        else if (action === "page") accepted = periods.setPage(value, false)
        else if (action === "revision") accepted = periods.loadRevision(value, false)
        else accepted = periods.reload(false)
        if (!accepted && editorState.dirty && editorState.error === "unsaved_complaint_period_changes") {
            pendingAction = action
            pendingValue = value
            discardDialog.open()
        }
        restorePicker()
    }
    function gotoPeriod() {
        var input = gotoField.text.trim()
        var ordinal = /^[0-9]+$/.test(input) ? Number(input) : 0
        if (!isFinite(ordinal) || Math.floor(ordinal) !== ordinal
                || ordinal < 1 || ordinal > editorState.period_count) ordinal = 0
        choose("period", ordinal)
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
    component ActionButton: FormButton {
        id: actionControl
        Layout.fillWidth: true
        implicitWidth: 160
        implicitHeight: Math.max(48, actionLabel.implicitHeight + 24)
        contentItem: Text {
            id: actionLabel
            text: actionControl.text
            textFormat: Text.PlainText
            font: actionControl.font
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: actionControl.enabled ? (actionControl.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component ReasonTextArea: TextArea {
        id: field
        property string caption: ""
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.WordWrap
        clip: true
        selectByMouse: true
        enabled: !page.editorState.busy
        leftPadding: 12
        rightPadding: 12
        topPadding: 12
        bottomPadding: 12
        topInset: 0
        Accessible.name: caption
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
        background: Rectangle {
            radius: 8
            color: "white"
            border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: field.activeFocus ? 2 : 1
        }
    }

    Connections {
        target: page.periods
        function onErasePassword() { approvalPassword.clear() }
        function onStateChanged() { Qt.callLater(function() { page.restorePicker() }) }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("complaint_period_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "complaintPeriodRefresh"
            text: page.t("refresh"); flat: true; highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            enabled: page.hasStation && !working
            onClicked: page.periods.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("complaint_period_intro") }
    FormNotice {
        objectName: "complaintPeriodNotice"
        words: page.words; error: page.editorState.error; notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        objectName: "complaintPeriodNewerWarning"
        visible: !!page.editorState.newer_revision
        text: page.t("complaint_period_newer"); color: "#8a5c16"
    }
    FormCaption { visible: !page.hasStation; text: page.t("select_station") }
    FormPanel {
        visible: page.hasStation
        implicitHeight: coverage.implicitHeight + 40
        ColumnLayout {
            id: coverage
            anchors.fill: parent; anchors.margins: 20; spacing: 16
            Heading { text: page.t("complaint_period_coverage") }
            FormCaption { text: page.t("complaint_period_coverage_hint") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 900 ? 4 : 2
                columnSpacing: 24; rowSpacing: 16
                Detail { caption: page.t("complaint_period_required"); value: page.summary.required_display || "—" }
                Detail { caption: page.t("complaint_period_missing"); value: page.summary.missing_display || "—" }
                Detail { caption: page.t("complaint_period_approved_current"); value: page.summary.approved_current_display || "—" }
                Detail { caption: page.t("complaint_period_outside"); value: page.editorState.outside_coverage_case_count_display || "—" }
            }
            Heading { text: page.t("complaint_period_schedule"); font.pixelSize: 17 }
            FormCaption {
                visible: page.editorState.schedule_state !== "configured"
                text: page.t("schedule_not_configured")
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 780 ? 2 : 1
                columnSpacing: 24; rowSpacing: 16
                Detail { caption: page.t("planned_opening"); value: page.time(page.schedule.planned_opening_at) }
                Detail { caption: page.t("planned_closing"); value: page.time(page.schedule.planned_closing_at) }
            }
            FormCaption {
                text: page.t("reporting_interval") + " · " + (page.schedule.reporting_interval_minutes || "—")
                    + "   " + page.t("complaint_period_total_periods") + " · " + page.editorState.period_count_display
            }
        }
    }
    FormPanel {
        visible: page.hasStation
        implicitHeight: navigation.implicitHeight + 40
        ColumnLayout {
            id: navigation
            anchors.fill: parent
            anchors.margins: 20
            spacing: 14
            Heading { text: page.t("complaint_period_select_period") }
            ComboBox {
                id: periodPicker
                objectName: "complaintPeriodPeriodPicker"
                Layout.fillWidth: true
                model: page.editorState.items
                currentIndex: page.selectedIndex()
                displayText: currentIndex >= 0 && currentIndex < model.length
                    ? page.periodLabel(model[currentIndex]) : page.t("complaint_period_select_period")
                enabled: !page.editorState.busy
                implicitHeight: Math.max(48, pickerText.implicitHeight + 24)
                Accessible.name: page.t("complaint_period_select_period")
                contentItem: Text {
                    id: pickerText
                    text: periodPicker.displayText
                    textFormat: Text.PlainText
                    font: periodPicker.font
                    color: "#25344b"
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: option
                    required property var modelData
                    required property int index
                    width: periodPicker.width
                    highlighted: periodPicker.highlightedIndex === index
                    implicitHeight: Math.max(48, optionText.implicitHeight + 20)
                    contentItem: Text {
                        id: optionText
                        text: page.periodLabel(option.modelData)
                        textFormat: Text.PlainText
                        font: option.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: index => {
                    var row = model[index]
                    if (row) page.choose("period", row.period_index)
                    page.restorePicker()
                }
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (periodPicker.activeFocus) page.reveal(periodPicker)
                })
            }
            FormCaption {
                text: page.t("complaint_period_visible_periods") + " · " + page.editorState.items.length
                    + " / " + page.editorState.period_count_display
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 640 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 12
                ActionButton {
                    objectName: "complaintPeriodPreviousPage"
                    text: page.t("complaint_period_previous_page")
                    highlighted: false
                    flat: true
                    working: page.editorState.busy
                    enabled: !working && page.editorState.offset > 0
                    onClicked: page.choose("page", Math.max(0, page.editorState.offset - page.editorState.limit))
                }
                ActionButton {
                    objectName: "complaintPeriodNextPage"
                    text: page.t("complaint_period_next_page")
                    highlighted: false
                    flat: true
                    working: page.editorState.busy
                    enabled: !working && page.editorState.offset + page.editorState.limit < page.editorState.period_count
                    onClicked: page.choose("page", page.editorState.offset + page.editorState.limit)
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 640 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 8
                FormField {
                    id: gotoField
                    objectName: "complaintPeriodGotoPeriod"
                    maximumLength: 10
                    placeholderText: page.t("complaint_period_goto_period")
                    working: page.editorState.busy
                    Accessible.name: page.t("complaint_period_goto_period")
                    onAccepted: page.gotoPeriod()
                    onReveal: control => page.reveal(control)
                }
                ActionButton {
                    objectName: "complaintPeriodGotoButton"
                    text: page.t("complaint_period_goto")
                    highlighted: false
                    working: page.editorState.busy
                    enabled: !working && !!gotoField.text.trim()
                    onClicked: page.gotoPeriod()
                }
            }
            ActionButton {
                objectName: "complaintPeriodReload"
                text: page.t("reload_saved")
                highlighted: false
                flat: true
                working: page.editorState.busy
                onClicked: page.choose("reload", 0)
            }
        }
    }

    FormPanel {
        visible: page.hasStation && page.hasReviewedPeriod
        implicitHeight: reviewed.implicitHeight + 40
        ColumnLayout {
            id: reviewed
            anchors.fill: parent; anchors.margins: 20; spacing: 16
            Heading { text: page.t("complaint_period_reviewed") }
            FormCaption { text: page.t("complaint_period_frozen_hint") }
            FormCaption {
                visible: !!page.editorState.historical
                text: page.t("complaint_historical_readonly"); color: "#8a5c16"
            }
            FormCaption {
                objectName: "complaintPeriodMissing"
                visible: !page.selected.revision
                text: page.t("complaint_period_missing_hint")
            }
            FormCaption {
                text: page.t("complaint_period_period") + " " + (page.reviewedPeriod.period_index_display || "—")
                    + " · " + page.t(page.selected.status || "missing") + " · " + page.t("revision")
                    + " " + (page.selected.revision || "—")
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 780 ? 2 : 1
                columnSpacing: 24; rowSpacing: 16
                Detail { caption: page.t("complaint_period_start"); value: page.time(page.reviewedPeriod.start_at) }
                Detail { caption: page.t("complaint_period_end"); value: page.time(page.reviewedPeriod.end_at) }
                Detail { objectName: "complaintPeriodReceivedTotal"; caption: page.t("complaint_period_received"); value: page.selected.total_received_display || "—" }
                Detail { caption: page.t("complaint_period_completed"); value: page.selected.total_completed_display || "—" }
                Detail { caption: page.t("complaint_period_in_progress"); value: page.selected.total_in_progress_display || "—" }
                Detail { caption: page.t("complaint_period_basis_at"); value: page.time(page.selected.basis_at) }
                Detail { caption: page.t("server_entry"); value: page.time(page.selected.entered_at) + (page.selected.actor_id ? "\n" + page.t("entered_by") + " " + page.selected.actor_id : "") }
                Detail { caption: page.t("submission"); value: page.selected.submitted_at ? page.time(page.selected.submitted_at) + "\n" + page.t("submitted_by") + " " + page.selected.submitted_by : "—" }
                Detail { caption: page.t("approval"); value: page.selected.approved_at ? page.time(page.selected.approved_at) + "\n" + page.t("approved_by") + " " + page.selected.approved_by : "—" }
            }
            Detail { visible: !!page.selected.amendment_reason; caption: page.t("amendment_reason"); value: page.selected.amendment_reason || "—" }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
            Heading { text: page.t("complaint_period_live_basis"); font.pixelSize: 17 }
            FormCaption { text: page.t("complaint_period_live_hint") }
            FormCaption {
                objectName: "complaintPeriodLiveValidity"
                text: !page.current.record ? page.t("complaint_period_missing_hint")
                    : page.t(page.current.review_required ? "complaint_period_needs_review"
                    : page.current.approval_valid ? "complaint_period_valid_approval"
                    : page.current.basis_current ? "complaint_period_basis_matches" : "complaint_period_basis_changed")
                color: page.current.review_required ? "#8a5c16" : "#42536c"
            }
            Heading { visible: !!page.selected.revision; text: page.t("complaint_period_groups"); font.pixelSize: 17 }
            FormCaption { visible: !!page.selected.revision && !(page.selected.group_counts || []).length; text: page.t("complaint_period_zero") }
            Repeater {
                model: page.selected.group_counts || []
                delegate: ColumnLayout {
                    id: group
                    required property var modelData
                    Layout.fillWidth: true; spacing: 8
                    Heading { text: group.modelData.code + " · " + page.categoryLabel(group.modelData, false); font.pixelSize: 17 }
                    FormCaption { text: page.t("complaint_period_category_revision") + " " + group.modelData.category_revision + " · " + page.t(group.modelData.verified_source ? "complaint_verified_reference" : "complaint_project_configured") }
                    FormCaption { visible: !!group.modelData.source_english; text: group.modelData.source_english || "" }
                    FormCaption { visible: !!group.modelData.reference_page; text: page.t("complaint_reference_page") + " " + (group.modelData.reference_page || "") }
                    FormCaption { text: page.t("complaint_translation_note") }
                    FormCaption { text: page.t("complaint_period_received") + " " + group.modelData.total_received_display + " · " + page.t("complaint_period_completed") + " " + group.modelData.total_completed_display + " · " + page.t("complaint_period_in_progress") + " " + group.modelData.total_in_progress_display }
                }
            }
            Heading { visible: !!page.selected.revision; text: page.t("complaint_period_members"); font.pixelSize: 17 }
            Repeater {
                model: page.selected.members || []
                delegate: ColumnLayout {
                    id: member
                    required property var modelData
                    Layout.fillWidth: true; spacing: 8
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
                    Heading { text: member.modelData.case_reference; font.pixelSize: 17 }
                    FormCaption { text: page.t("complaint_period_case_revision") + " " + member.modelData.revision + " · " + page.t("complaint_period_case_id") + " " + member.modelData.case_id + " · " + page.t("complaint_period_case_revision_id") + " " + member.modelData.case_revision_id }
                    FormCaption { text: member.modelData.category_code + " · " + page.categoryLabel(member.modelData, true) + " · " + page.t("complaint_period_category_revision") + " " + member.modelData.category_revision }
                    FormCaption { text: page.t("complaint_" + member.modelData.work_status) + " · " + page.t("complaint_received_time") + " " + page.time(member.modelData.received_at) }
                    FormCaption { text: page.t("complaint_completed_time") + " " + page.time(member.modelData.completed_at) }
                    FormCaption { text: page.t("server_entry") + " " + page.time(member.modelData.entered_at) + " · " + page.t("entered_by") + " " + member.modelData.actor_id }
                }
            }
        }
    }
    FormPanel {
        visible: page.hasStation && page.pollingOfficer && page.hasReviewedPeriod
        implicitHeight: actions.implicitHeight + 40
        ColumnLayout {
            id: actions
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("complaint_period_actions") }
            FormCaption { text: page.t("complaint_period_prepare_hint") }
            FormCaption { visible: !page.activeElection; text: page.t("election_read_only") }
            FormCaption { visible: page.amendable; text: page.t("amendment_reason") }
            ReasonTextArea {
                objectName: "complaintPeriodReason"
                visible: page.amendable
                text: page.form.reason || ""
                readOnly: !page.editable || !page.amendable
                caption: page.t("amendment_reason")
                onTextChanged: if (activeFocus) page.periods.setReason(text)
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 900 ? 3 : 1
                columnSpacing: 12; rowSpacing: 8
                ActionButton {
                    objectName: "complaintPeriodPrepare"
                    visible: page.pollingOfficer
                    text: page.t("complaint_period_prepare")
                    working: page.editorState.busy
                    enabled: page.editable && page.draft && !page.editorState.newer_revision
                    onClicked: page.periods.prepare()
                }
                ActionButton {
                    objectName: "complaintPeriodSubmit"
                    visible: page.pollingOfficer
                    text: page.t("complaint_period_submit")
                    working: page.editorState.busy
                    enabled: page.editable && page.selected.status === "draft" && !!page.current.basis_current
                        && !page.editorState.dirty && !page.editorState.newer_revision
                    onClicked: page.periods.submit()
                }
                ActionButton {
                    objectName: "complaintPeriodAmend"
                    visible: page.amendable
                    text: page.t("complaint_period_amend")
                    working: page.editorState.busy
                    enabled: page.editable && page.amendable && !page.editorState.newer_revision && !!(page.form.reason || "").trim()
                    onClicked: page.periods.amend()
                }
            }
        }
    }
    FormPanel {
        visible: page.hasStation && page.supervisor && page.hasReviewedPeriod
        implicitHeight: approval.implicitHeight + 40
        ColumnLayout {
            id: approval
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("complaint_period_approve") }
            FormCaption { text: page.t("complaint_period_approval_hint") }
            FormCaption { text: page.t("complaint_period_period") + " " + (page.reviewedPeriod.period_index_display || "—") + " · " + page.t("revision") + " " + (page.selected.revision || "—") }
            FormCaption { text: page.t("approval_password") }
            FormField {
                id: approvalPassword
                objectName: "complaintPeriodPassword"
                echoMode: TextInput.Password; maximumLength: 128
                working: page.editorState.busy; enabled: page.canApprove
                Accessible.name: page.t("approval_password")
                onReveal: control => page.reveal(control)
            }
            ActionButton {
                objectName: "complaintPeriodApprove"
                text: page.t("complaint_period_approve")
                working: page.editorState.busy
                enabled: page.canApprove && approvalPassword.text.length > 0
                onClicked: page.periods.approve(approvalPassword.text)
            }
        }
    }
    FormPanel {
        visible: page.hasStation
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 16
            Heading { text: page.t("complaint_period_history") }
            FormCaption { visible: !page.editorState.history.length; text: page.t(page.editorState.busy || page.editorState.refreshing ? "loading" : "complaint_period_no_history") }
            Repeater {
                model: page.editorState.history
                delegate: ColumnLayout {
                    id: entry
                    required property var modelData
                    Layout.fillWidth: true; spacing: 12
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
                    Heading { text: page.t("revision") + " " + entry.modelData.revision + " · " + page.t(entry.modelData.status); font.pixelSize: 17 }
                    ActionButton {
                        objectName: "complaintPeriodHistoryRevision" + entry.modelData.revision
                        text: page.t("complaint_period_view_revision") + " · " + page.t("revision") + " " + entry.modelData.revision
                        highlighted: false; flat: true; working: page.editorState.busy
                        onClicked: page.choose("revision", entry.modelData.revision)
                    }
                    FormCaption { text: page.t("complaint_period_received") + " " + entry.modelData.total_received_display + " · " + page.t("complaint_period_completed") + " " + entry.modelData.total_completed_display + " · " + page.t("complaint_period_in_progress") + " " + entry.modelData.total_in_progress_display }
                    FormCaption { text: page.t("complaint_period_basis_at") + " " + page.time(entry.modelData.basis_at) }
                    FormCaption { text: page.t("server_entry") + " " + page.time(entry.modelData.entered_at) + " · " + page.t("entered_by") + " " + entry.modelData.actor_id }
                    FormCaption { visible: !!entry.modelData.submitted_at; text: page.t("submission") + " " + page.time(entry.modelData.submitted_at) + " · " + page.t("submitted_by") + " " + (entry.modelData.submitted_by || "—") }
                    FormCaption { visible: !!entry.modelData.approved_at; text: page.t("approval") + " " + page.time(entry.modelData.approved_at) + " · " + page.t("approved_by") + " " + (entry.modelData.approved_by || "—") }
                    Detail { caption: page.t("amendment_reason"); value: entry.modelData.amendment_reason || "—" }
                }
            }
        }
    }
    FormPanel {
        visible: page.hasStation
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("complaint_period_report") }
            FormCaption { text: page.t("complaint_period_report_hint") }
            FormCaption { text: page.t("complaint_period_report_scope") }
            ComboBox {
                id: reportScope
                objectName: "complaintPeriodReportScope"
                Layout.fillWidth: true
                model: [page.t("complaint_period_report_selected"), page.t("complaint_period_report_station")]
                enabled: !page.editorState.busy
                implicitHeight: Math.max(48, scopeText.implicitHeight + 24)
                Accessible.name: page.t("complaint_period_report_scope")
                contentItem: Text {
                    id: scopeText
                    text: reportScope.displayText
                    textFormat: Text.PlainText
                    font: reportScope.font
                    color: "#25344b"
                    wrapMode: Text.WordWrap
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: scopeOption
                    required property string modelData
                    required property int index
                    width: reportScope.width
                    highlighted: reportScope.highlightedIndex === index
                    implicitHeight: Math.max(48, scopeOptionText.implicitHeight + 20)
                    contentItem: Text {
                        id: scopeOptionText
                        text: scopeOption.modelData
                        textFormat: Text.PlainText
                        font: scopeOption.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (reportScope.activeFocus) page.reveal(reportScope)
                })
            }
            FormCaption {
                text: page.t(reportScope.currentIndex === 1
                    ? "complaint_period_report_station_hint" : "complaint_period_report_selected_hint")
            }
            FormCaption {
                visible: reportScope.currentIndex === 0 && !page.selected.revision
                text: page.t("complaint_period_report_missing")
            }
            FormCaption {
                text: page.t("stock_report_language") + " · " + page.languageName(page.locale)
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 8
                ActionButton {
                    objectName: "complaintPeriodPreview"
                    text: page.t("stock_preview")
                    working: page.editorState.busy
                    enabled: !working && (reportScope.currentIndex === 1 || !!page.selected.revision)
                    onClicked: page.previewReport()
                }
                ActionButton {
                    objectName: "complaintPeriodExportPdf"
                    text: page.t("stock_export_pdf")
                    working: page.editorState.busy
                    highlighted: false
                    enabled: !working && (reportScope.currentIndex === 1 || !!page.selected.revision)
                    onClicked: page.exportReport("pdf")
                }
                ActionButton {
                    objectName: "complaintPeriodExportCsv"
                    text: page.t("stock_export_csv")
                    working: page.editorState.busy
                    highlighted: false
                    enabled: !working && (reportScope.currentIndex === 1 || !!page.selected.revision)
                    onClicked: page.exportReport("csv")
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · "
                    + page.languageName((page.editorState.report || ({})).locale || page.locale)
                    + "\n" + page.t((page.editorState.report || ({})).report_scope === "station_current"
                        ? "complaint_period_report_station" : "complaint_period_report_selected")
            }
            ReasonTextArea {
                objectName: "complaintPeriodReportPreview"
                visible: !!page.editorState.report_text
                readOnly: true
                text: page.editorState.report_text || ""
                caption: page.t("complaint_period_report")
            }
            FormCaption {
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        objectName: "complaintPeriodDiscardDialog"
        title: page.t("discard_changes")
        message: page.t("unsaved_complaint_period_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            if (page.pendingAction === "period") page.periods.selectPeriod(page.pendingValue, true)
            else if (page.pendingAction === "page") page.periods.setPage(page.pendingValue, true)
            else if (page.pendingAction === "revision") page.periods.loadRevision(page.pendingValue, true)
            else page.periods.reload(true)
            page.restorePicker()
        }
    }
    FileDialog {
        id: exportDialog
        objectName: "complaintPeriodExportDialog"
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.periods.download(page.pendingFormat, selectedFile.toString(),
            page.pendingLocale, page.pendingStationReport)
    }
}
