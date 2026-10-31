import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts

ApplicationWindow {
    id: window
    visible: true
    width: 1280
    height: 800
    minimumWidth: 900
    minimumHeight: 480
    title: "Election Management and Voting System"
    color: "#f6f8fc"
    Material.theme: Material.Light
    Material.accent: "#1967d2"
    Material.primary: "#1967d2"
    font.family: Qt.platform.os === "windows" ? "Microsoft JhengHei UI" : "PingFang TC"
    font.pixelSize: 14

    readonly property var state: controller.state
    readonly property var words: controller.texts
    readonly property bool signedIn: state.phase !== "signed_out"
    readonly property color ink: "#25344b"
    readonly property color muted: "#65758b"
    readonly property color accent: "#1967d2"
    readonly property color line: "#e1e7f0"
    readonly property bool administrator: state.account.role === "administrator"
    property string currentPage: "account"
    readonly property bool stationPage: ["polling", "stock", "allocations", "stockSnapshots", "specialPapers", "counterReturns", "turnout", "fallback", "complaints",
        "complaintPeriods", "queue", "boxes", "accounting", "countingScopes", "countingRounds", "recovery", "outages", "constituency_results"].indexOf(currentPage) >= 0
    onSignedInChanged: if (!signedIn) currentPage = "account"
    onAdministratorChanged: if (!administrator) currentPage = "account"
    onCurrentPageChanged: Qt.callLater(function() { if (scroll.contentItem) scroll.contentItem.contentY = 0 })
    onActiveFocusItemChanged: Qt.callLater(function() {
        window.revealIn(sidebarScroll, window.activeFocusItem)
    })

    function t(key) { return words[key] || key }
    function submitLogin() { controller.signIn(serverField.text, usernameField.text, passwordField.text) }
    function submitPassword() { controller.changePassword(currentField.text, newField.text, confirmField.text) }
    function revealIn(scrollView, control) {
        if (!control || !scrollView || !scrollView.contentItem) return
        var ancestor = control
        while (ancestor && ancestor !== scrollView) ancestor = ancestor.parent
        if (ancestor !== scrollView) return
        var viewport = scrollView.contentItem
        var origin = control.mapToItem(viewport, 0, 0)
        var target = viewport.contentY
        if (origin.y < 12) target += origin.y - 12
        else if (origin.y + control.height > viewport.height - 12)
            target += origin.y + control.height - viewport.height + 12
        viewport.contentY = Math.max(0, Math.min(target,
            Math.max(0, viewport.contentHeight - viewport.height)))
    }
    function revealField(control) { revealIn(scroll, control) }

    Connections {
        target: scroll.contentItem
        function onContentHeightChanged() {
            Qt.callLater(function() {
                var control = window.activeFocusItem
                if (control && control.cursorPosition !== undefined && control.readOnly !== true)
                    window.revealField(control)
            })
        }
    }

    Connections {
        target: controller
        function onEraseSecrets() {
            passwordField.clear()
            currentField.clear()
            newField.clear()
            confirmField.clear()
        }
    }

    component Caption: Label {
        color: window.muted
        font.pixelSize: 12
        wrapMode: Text.WordWrap
        textFormat: Text.PlainText
    }
    component Field: TextField {
        id: fieldControl
        Layout.fillWidth: true
        implicitHeight: 48
        selectByMouse: true
        enabled: !window.state.busy
        font.pixelSize: 14
        Material.containerStyle: Material.Outlined
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { window.revealField(fieldControl) })
    }
    component PrimaryButton: Button {
        id: primaryControl
        highlighted: true
        implicitHeight: 48
        font.pixelSize: 14
        font.weight: Font.Medium
        enabled: !window.state.busy
        Material.roundedScale: Material.FullScale
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { window.revealField(primaryControl) })
    }
    component Panel: Rectangle {
        color: "white"
        radius: 18
        border.color: window.line
    }
    component Detail: ColumnLayout {
        property string caption
        property string value
        spacing: 5
        Caption { text: parent.caption; Layout.fillWidth: true }
        Label {
            text: parent.value
            color: window.ink
            font.pixelSize: 15
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
            textFormat: Text.PlainText
        }
    }

    header: Rectangle {
        height: 88
        color: "white"
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: window.line }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            spacing: 16
            Rectangle {
                width: 44; height: 44; radius: 14; color: window.accent
                Label { anchors.centerIn: parent; text: "E"; font.pixelSize: 24; font.weight: Font.Medium; color: "white" }
                Accessible.ignored: true
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.minimumWidth: 180
                Layout.maximumWidth: 480
                spacing: 3
                Label { text: window.t("app_name"); color: window.ink; font.pixelSize: 20; font.weight: Font.Medium; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                Caption {
                    text: window.signedIn ? window.t(window.state.account.role || "") + " · " + (window.state.account.username || "") : window.t("election_management")
                    font.pixelSize: 11
                    Layout.fillWidth: true
                    wrapMode: Text.NoWrap
                    elide: Text.ElideRight
                }
            }
            Item { Layout.fillWidth: true }
            RowLayout {
                Layout.minimumWidth: 80
                Layout.maximumWidth: 180
                spacing: 8
                Rectangle {
                    width: 7; height: 7; radius: 4
                    color: window.state.connection === "connected" ? "#238467" : "#b47716"
                    Accessible.ignored: true
                }
                Caption {
                    text: window.t(window.state.connection)
                    color: window.state.connection === "connected" ? "#238467" : window.muted
                    Layout.maximumWidth: 180
                    Layout.fillWidth: true
                }
            }
            Button {
                text: window.t("refresh")
                flat: true
                onClicked: controller.refresh()
                Accessible.name: window.t("refresh")
            }
            ComboBox {
                id: languageBox
                implicitWidth: 132
                model: [{label: "繁體中文", code: "tc"}, {label: "简体中文", code: "sc"}, {label: "English", code: "en"}]
                textRole: "label"
                valueRole: "code"
                currentIndex: window.state.locale === "sc" ? 1 : window.state.locale === "en" ? 2 : 0
                onActivated: controller.setLocale(currentValue)
                Accessible.name: window.t("language")
            }
        }
    }

    footer: Rectangle {
        height: 44
        color: "white"
        Rectangle { width: parent.width; height: 1; color: window.line }
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 24; anchors.rightMargin: 24
            Caption { text: window.t("last_refresh") + "  " + window.state.last_refresh }
            Item { Layout.fillWidth: true }
            Caption { text: window.state.clock; font.family: Qt.platform.os === "windows" ? "Consolas" : "Menlo" }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0
        Rectangle {
            id: sidebar
            visible: window.signedIn && window.state.phase === "workspace"
            Layout.preferredWidth: 208
            Layout.fillHeight: true
            color: "#edf3fc"
            ScrollView {
                id: sidebarScroll
                anchors.fill: parent
                clip: true
                contentWidth: availableWidth
                onHeightChanged: Qt.callLater(function() {
                    window.revealIn(sidebarScroll, window.activeFocusItem)
                })
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: sidebarScroll.availableWidth - 36
                x: 18; y: 18
                height: Math.max(implicitHeight, sidebarScroll.availableHeight - 36)
                spacing: 8
                Caption { text: window.t("workspace"); Layout.topMargin: 10; Layout.bottomMargin: 12 }
                Button {
                    objectName: "accountNavigation"
                    text: window.t("account"); Layout.fillWidth: true
                    highlighted: window.currentPage === "account"; flat: true
                    Material.background: window.currentPage === "account" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: window.currentPage = "account"
                }
                Button {
                    text: window.t("election_setup"); Layout.fillWidth: true
                    visible: window.state.account.role === "administrator"
                    highlighted: window.currentPage === "setup"; flat: true
                    Material.background: window.currentPage === "setup" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: { window.currentPage = "setup"; controller.configuration.open() }
                }
                Button {
                    text: window.t("station_setup"); Layout.fillWidth: true
                    visible: window.state.account.role === "administrator"
                    highlighted: window.currentPage === "stations"; flat: true
                    Material.background: window.currentPage === "stations" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: { window.currentPage = "stations"; controller.configuration.open() }
                }
                Button {
                    text: window.t("election_schedule"); Layout.fillWidth: true
                    visible: window.administrator
                    highlighted: window.currentPage === "schedule"; flat: true
                    Material.background: window.currentPage === "schedule" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: { window.currentPage = "schedule"; controller.lifecycle.open() }
                }
                Button {
                    id: categoriesNavigation
                    objectName: "complaintCategoriesNavigation"
                    text: window.t("complaint_categories")
                    Layout.fillWidth: true
                    implicitHeight: Math.max(48, categoriesNavigationText.implicitHeight + 24)
                    visible: window.administrator
                    highlighted: window.currentPage === "complaintCategories"
                    flat: true
                    Material.roundedScale: Material.FullScale
                    contentItem: Text {
                        id: categoriesNavigationText
                        text: categoriesNavigation.text
                        textFormat: Text.PlainText
                        font: categoriesNavigation.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "complaintCategories"
                        controller.complaintCategories.open()
                    }
                }
                Button {
                    id: invalidReasonsNavigation
                    objectName: "invalidReasonsNavigation"
                    text: window.t("invalid_reasons_title")
                    Layout.fillWidth: true
                    implicitHeight: Math.max(48, invalidReasonsNavigationText.implicitHeight + 24)
                    visible: window.administrator
                    highlighted: window.currentPage === "invalidReasons"
                    flat: true
                    Material.roundedScale: Material.FullScale
                    contentItem: Text {
                        id: invalidReasonsNavigationText
                        text: invalidReasonsNavigation.text
                        textFormat: Text.PlainText
                        font: invalidReasonsNavigation.font
                        color: "#25344b"
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "invalidReasons"
                        controller.invalidReasons.open()
                    }
                }
                Button {
                    objectName: "serverBackupsNavigation"
                    text: window.t("server_backups_navigation"); Layout.fillWidth: true
                    visible: window.administrator
                    highlighted: window.currentPage === "serverBackups"; flat: true
                    Material.background: window.currentPage === "serverBackups" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: { window.currentPage = "serverBackups"; controller.serverBackups.open() }
                }
                Button {
                    text: window.t("staff_accounts"); Layout.fillWidth: true
                    visible: window.administrator
                    highlighted: window.currentPage === "staff"; flat: true
                    Material.background: window.currentPage === "staff" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: { window.currentPage = "staff"; controller.staff.open() }
                }
                Button {
                    text: window.t("polling"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "polling"
                    Material.background: window.currentPage === "polling" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    onClicked: {
                        window.currentPage = "polling"
                        controller.workspace.open()
                        controller.polling.open()
                    }
                }
                Button {
                    id: stockNavigation
                    text: window.t("received_stock"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "stock"
                    Material.background: window.currentPage === "stock" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: stockNavigation.text
                        textFormat: Text.PlainText
                        font: stockNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "stock"
                        controller.workspace.open()
                        controller.stock.open()
                    }
                }
                Button {
                    id: allocationNavigation
                    objectName: "allocationNavigation"
                    text: window.t("allocation_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "allocations"
                    Material.background: window.currentPage === "allocations" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: allocationNavigation.text
                        textFormat: Text.PlainText
                        font: allocationNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "allocations"
                        controller.workspace.open()
                        controller.allocations.open()
                    }
                }
                Button {
                    id: stockSnapshotsNavigation
                    objectName: "stockSnapshotsNavigation"
                    text: window.t("snapshot_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "stockSnapshots"
                    Material.background: window.currentPage === "stockSnapshots" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: stockSnapshotsNavigation.text
                        textFormat: Text.PlainText
                        font: stockSnapshotsNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "stockSnapshots"
                        controller.workspace.open()
                        controller.stockSnapshots.open()
                    }
                }
                Button {
                    id: specialPapersNavigation
                    objectName: "specialPapersNavigation"
                    text: window.t("special_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "specialPapers"
                    Material.background: window.currentPage === "specialPapers" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: specialPapersNavigation.text
                        textFormat: Text.PlainText
                        font: specialPapersNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "specialPapers"
                        controller.workspace.open()
                        controller.specialPapers.open()
                    }
                }
                Button {
                    id: counterReturnsNavigation
                    objectName: "counterReturnsNavigation"
                    text: window.t("counter_return_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "counterReturns"
                    Material.background: window.currentPage === "counterReturns" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: counterReturnsNavigation.text
                        textFormat: Text.PlainText; font: counterReturnsNavigation.font
                        color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "counterReturns"
                        controller.workspace.open()
                        controller.counterReturns.open()
                    }
                }
                Button {
                    id: turnoutNavigation
                    objectName: "turnoutNavigation"
                    text: window.t("turnout_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "turnout"
                    Material.background: window.currentPage === "turnout" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: turnoutNavigation.text; textFormat: Text.PlainText; font: turnoutNavigation.font
                        color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "turnout"
                        controller.workspace.open()
                        controller.turnout.open()
                    }
                }
                Button {
                    id: fallbackNavigation
                    objectName: "fallbackNavigation"
                    text: window.t("fallback_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "fallback"
                    Material.background: window.currentPage === "fallback" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: fallbackNavigation.text; textFormat: Text.PlainText
                        font: fallbackNavigation.font; color: window.ink
                        wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "fallback"
                        controller.workspace.open()
                        controller.fallback.open()
                    }
                }
                Button {
                    id: complaintsNavigation
                    objectName: "complaintsNavigation"
                    text: window.t("complaint_cases"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "complaints"
                    Material.background: window.currentPage === "complaints" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: complaintsNavigation.text
                        textFormat: Text.PlainText
                        font: complaintsNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "complaints"
                        controller.workspace.open()
                        controller.complaints.open()
                    }
                }
                Button {
                    id: complaintPeriodsNavigation
                    objectName: "complaintPeriodsNavigation"
                    text: window.t("complaint_period_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "complaintPeriods"
                    Material.background: window.currentPage === "complaintPeriods" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: complaintPeriodsNavigation.text
                        textFormat: Text.PlainText
                        font: complaintPeriodsNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "complaintPeriods"
                        controller.workspace.open()
                        controller.complaintPeriods.open()
                    }
                }
                Button {
                    id: queueNavigation
                    objectName: "queueNavigation"
                    text: window.t("queue"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "queue"
                    Material.background: window.currentPage === "queue" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: queueNavigation.text
                        textFormat: Text.PlainText
                        font: queueNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "queue"
                        controller.workspace.open()
                        var context = controller.workspace.state.selected
                        controller.queue.open((context.station || ({})).id || 0, window.state.account.role)
                    }
                }
                Button {
                    id: boxesNavigation
                    objectName: "boxesNavigation"
                    text: window.t("boxes"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "boxes"
                    Material.background: window.currentPage === "boxes" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: boxesNavigation.text; textFormat: Text.PlainText; font: boxesNavigation.font
                        color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "boxes"
                        controller.workspace.open()
                        controller.boxes.open()
                    }
                }
                Button {
                    id: accountingNavigation
                    objectName: "accountingNavigation"
                    text: window.t("accounting_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "accounting"
                    Material.background: window.currentPage === "accounting" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: accountingNavigation.text; textFormat: Text.PlainText; font: accountingNavigation.font
                        color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "accounting"
                        controller.workspace.open()
                        controller.accounting.open()
                    }
                }
                Button {
                    id: countingScopesNavigation
                    objectName: "countingScopesNavigation"
                    text: window.t("counting_scopes_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "countingScopes"
                    Material.background: window.currentPage === "countingScopes" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: countingScopesNavigation.text; textFormat: Text.PlainText
                        font: countingScopesNavigation.font; color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "countingScopes"
                        controller.workspace.open()
                        controller.countingScopes.open()
                    }
                }
                Button {
                    id: countingRoundsNavigation
                    objectName: "countingRoundsNavigation"
                    text: window.t("f1_title"); Layout.fillWidth: true; flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "countingRounds"
                    Material.background: window.currentPage === "countingRounds" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: countingRoundsNavigation.text; textFormat: Text.PlainText
                        font: countingRoundsNavigation.font; color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "countingRounds"
                        controller.workspace.open()
                        controller.countingRounds.open()
                    }
                }
                Button {
                    id: recoveryNavigation
                    objectName: "recoveryNavigation"
                    text: window.t("recovery_title")
                    Layout.fillWidth: true
                    flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "recovery"
                    Material.background: highlighted ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: recoveryNavigation.text
                        textFormat: Text.PlainText
                        font: recoveryNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "recovery"
                        controller.workspace.open()
                        controller.recovery.open()
                    }
                }
                Button {
                    id: outagesNavigation
                    objectName: "outagesNavigation"
                    text: window.t("outage_title")
                    Layout.fillWidth: true
                    flat: true
                    visible: !window.administrator
                    highlighted: window.currentPage === "outages"
                    Material.background: highlighted ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: outagesNavigation.text
                        textFormat: Text.PlainText
                        font: outagesNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "outages"
                        controller.workspace.open()
                        controller.outages.open()
                    }
                }
                Button {
                    id: constituencyResultsNavigation
                    objectName: "constituencyResultsNavigation"
                    text: window.t("constituency_results_title"); Layout.fillWidth: true; flat: true
                    visible: window.state.account.role === "supervisor"
                    highlighted: window.currentPage === "constituency_results"
                    Material.background: window.currentPage === "constituency_results" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: constituencyResultsNavigation.text; textFormat: Text.PlainText
                        font: constituencyResultsNavigation.font; color: window.ink; wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "constituency_results"
                        controller.workspace.open()
                        controller.constituencyResults.open()
                    }
                }
                Button {
                    id: electionCompletionNavigation
                    objectName: "electionCompletionNavigation"
                    text: window.t("election_completion_navigation")
                    Layout.fillWidth: true
                    flat: true
                    visible: window.state.account.role === "supervisor"
                    highlighted: window.currentPage === "election_completion"
                    Material.background: window.currentPage === "election_completion" ? "#dceaff" : "transparent"
                    Material.roundedScale: Material.FullScale
                    implicitHeight: Math.max(48, contentItem.implicitHeight + 20)
                    contentItem: Text {
                        text: electionCompletionNavigation.text
                        textFormat: Text.PlainText
                        font: electionCompletionNavigation.font
                        color: window.ink
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    onClicked: {
                        window.currentPage = "election_completion"
                        controller.electionCompletion.open()
                    }
                }
                Item { Layout.fillHeight: true }
                Caption { text: window.t("role") + " · " + window.t(window.state.account.role || ""); Layout.fillWidth: true }
                Button { text: window.t("logout"); flat: true; Layout.fillWidth: true; onClicked: controller.signOut() }
            }
            }
        }
        ScrollView {
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: scroll.availableWidth
                spacing: 0
                Item { Layout.preferredHeight: 24 }
                FormPanel {
                    visible: window.state.phase === "workspace"
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 16
                    implicitHeight: activeContext.implicitHeight + 24
                    color: "#edf3fc"
                    RowLayout {
                        id: activeContext
                        anchors.fill: parent; anchors.margins: 12
                        FormCaption { text: window.t("active_election"); Layout.fillWidth: false }
                        Label {
                            text: window.state.active_election ? window.state.active_election.name : window.t("no_active_election")
                            textFormat: Text.PlainText
                            color: window.ink; wrapMode: Text.WordWrap; Layout.fillWidth: true
                        }
                    }
                }
                Rectangle {
                    visible: !!window.state.error || !!window.state.notice
                    onVisibleChanged: if (visible) Qt.callLater(function() { window.revealField(window.activeFocusItem) })
                    Layout.fillWidth: true
                    Layout.leftMargin: 32; Layout.rightMargin: 32; Layout.bottomMargin: 18
                    implicitHeight: messageLabel.implicitHeight + 26
                    radius: 10
                    color: window.state.error ? "#fceceb" : "#e8f5ef"
                    Label {
                        id: messageLabel
                        anchors.fill: parent; anchors.margins: 13
                        text: window.t(window.state.error || window.state.notice)
                        color: window.state.error ? "#a52c27" : "#216a50"
                        wrapMode: Text.WordWrap
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                    }
                }

                RowLayout {
                    visible: !window.signedIn
                    Layout.fillWidth: true
                    Layout.leftMargin: 52; Layout.rightMargin: 52
                    Layout.topMargin: 12; Layout.bottomMargin: 38
                    spacing: 50
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 250
                        Layout.maximumWidth: 500
                        spacing: 24
                        Label { text: window.t("election_management"); color: window.accent; font.pixelSize: 12; font.letterSpacing: 1.2 }
                        Label { text: window.t("tagline"); color: window.ink; font.pixelSize: 35; font.weight: Font.Medium; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                        Rectangle { Layout.preferredWidth: 44; height: 4; radius: 2; color: window.accent }
                        Caption { text: window.t("connection_detail"); font.pixelSize: 15; Layout.fillWidth: true }
                        Item { Layout.preferredHeight: 26 }
                        Detail { caption: window.t("server"); value: window.state.server_url; Layout.fillWidth: true }
                        Caption { text: window.t("no_idle_lock"); Layout.fillWidth: true }
                    }
                    Panel {
                        Layout.preferredWidth: 420
                        implicitHeight: loginLayout.implicitHeight + 56
                        ColumnLayout {
                            id: loginLayout
                            anchors.fill: parent; anchors.margins: 28; spacing: 14
                            Caption { text: window.t("staff_access"); color: window.accent }
                            Label { text: window.t("welcome"); color: window.ink; font.pixelSize: 26; font.weight: Font.Medium; Layout.bottomMargin: 8 }
                            Label { text: window.t("server_address"); color: window.muted }
                            Field {
                                id: serverField; objectName: "serverAddress"
                                Component.onCompleted: text = window.state.server_url
                                Accessible.name: window.t("server_address")
                                placeholderText: "https://server.example:8443"
                                onEditingFinished: controller.configureServer(text)
                            }
                            Label { text: window.t("username"); color: window.muted }
                            Field {
                                id: usernameField; objectName: "username"
                                Accessible.name: window.t("username")
                                onAccepted: passwordField.forceActiveFocus()
                            }
                            Label { text: window.t("password"); color: window.muted }
                            Field {
                                id: passwordField; objectName: "password"
                                echoMode: TextInput.Password
                                Accessible.name: window.t("password")
                                onAccepted: window.submitLogin()
                            }
                            PrimaryButton {
                                text: window.t(window.state.busy ? "signing_in" : "sign_in"); Layout.fillWidth: true; Layout.topMargin: 8
                                onClicked: window.submitLogin()
                            }
                            BusyIndicator { running: window.state.busy; visible: running; Layout.alignment: Qt.AlignHCenter; implicitHeight: 28; implicitWidth: 28 }
                        }
                    }
                }

                ColumnLayout {
                    visible: window.state.phase === "password_change"
                    Layout.fillWidth: true
                    Layout.leftMargin: 36; Layout.rightMargin: 36; Layout.bottomMargin: 28
                    spacing: 20
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            Caption { text: window.t("first_login"); color: window.accent }
                            Label { text: window.t("change_password"); color: window.ink; font.pixelSize: 28; font.weight: Font.Medium }
                            Caption { text: window.t("signed_in_as") + "  " + (window.state.account.display_name || ""); Layout.fillWidth: true }
                        }
                        Button { text: window.t("logout"); flat: true; onClicked: controller.signOut() }
                    }
                    Panel {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.fillWidth: true; Layout.maximumWidth: 520
                        implicitHeight: changeLayout.implicitHeight + 48
                        ColumnLayout {
                            id: changeLayout
                            anchors.fill: parent; anchors.margins: 24; spacing: 12
                            Caption { text: window.t("password_hint"); Layout.fillWidth: true; Layout.bottomMargin: 6 }
                            Label { text: window.t("current_password"); color: window.muted }
                            Field { id: currentField; objectName: "currentPassword"; echoMode: TextInput.Password; Accessible.name: window.t("current_password"); onAccepted: newField.forceActiveFocus() }
                            Label { text: window.t("new_password"); color: window.muted }
                            Field { id: newField; objectName: "newPassword"; echoMode: TextInput.Password; Accessible.name: window.t("new_password"); onAccepted: confirmField.forceActiveFocus() }
                            Label { text: window.t("confirm_password"); color: window.muted }
                            Field { id: confirmField; objectName: "confirmPassword"; echoMode: TextInput.Password; Accessible.name: window.t("confirm_password"); onAccepted: window.submitPassword() }
                            PrimaryButton { text: window.t(window.state.busy ? "saving_password" : "save_password"); Layout.fillWidth: true; Layout.topMargin: 8; onClicked: window.submitPassword() }
                            BusyIndicator { running: window.state.busy; visible: running; implicitHeight: 28; implicitWidth: 28; Layout.alignment: Qt.AlignHCenter }
                        }
                    }
                }

                ColumnLayout {
                    visible: window.state.phase === "workspace" && window.currentPage === "account"
                    Layout.fillWidth: true
                    Layout.leftMargin: 32; Layout.rightMargin: 32; Layout.bottomMargin: 28
                    spacing: 24
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 6
                            Caption { text: window.t("workspace"); color: window.accent }
                            Label { text: window.t("user_profile"); color: window.ink; font.pixelSize: 28; font.weight: Font.Medium }
                        }
                        Item { Layout.fillWidth: true }
                        Rectangle {
                            radius: 16; color: "#e7f3ed"; implicitWidth: readyLabel.implicitWidth + 26; height: 32
                            Label { id: readyLabel; anchors.centerIn: parent; text: window.t("authenticated"); color: "#247355"; font.pixelSize: 12 }
                        }
                    }
                    Panel {
                        Layout.fillWidth: true
                        implicitHeight: accountLayout.implicitHeight + 48
                        GridLayout {
                            id: accountLayout
                            anchors.fill: parent; anchors.margins: 24
                            columns: 2; columnSpacing: 32; rowSpacing: 24
                            Detail { caption: window.t("account"); value: window.state.account.display_name || ""; Layout.fillWidth: true }
                            Detail { caption: window.t("username"); value: window.state.account.username || ""; Layout.fillWidth: true }
                            Detail { caption: window.t("role"); value: window.t(window.state.account.role || ""); Layout.fillWidth: true }
                            Detail { caption: window.t("session_expires"); value: window.state.expires; Layout.fillWidth: true }
                        }
                    }
                    Panel {
                        visible: !window.state.election
                        Layout.fillWidth: true
                        implicitHeight: emptyLayout.implicitHeight + 48
                        ColumnLayout {
                            id: emptyLayout
                            anchors.fill: parent; anchors.margins: 24; spacing: 12
                            Label { text: window.t("no_active_election"); font.pixelSize: 19; color: window.ink; font.weight: Font.Medium; Layout.fillWidth: true; wrapMode: Text.WordWrap }
                            Caption { text: window.t("activation_guidance"); Layout.fillWidth: true; font.pixelSize: 14 }
                            Rectangle { Layout.fillWidth: true; height: 1; color: window.line; Layout.topMargin: 8; Layout.bottomMargin: 8 }
                            Detail { caption: window.t("linked_server"); value: window.state.server_url; Layout.fillWidth: true }
                            Caption { text: window.t("no_idle_lock"); Layout.fillWidth: true }
                        }
                    }
                    StationWorkspace {
                        visible: !window.administrator
                        Layout.fillWidth: true
                        workspace: controller.workspace
                        words: window.words
                        onVisibleChanged: if (visible) controller.workspace.open()
                        onReveal: control => window.revealField(control)
                    }
                }
                ElectionSetup {
                    visible: window.state.phase === "workspace" && (window.currentPage === "setup" || window.currentPage === "stations") && window.state.account.role === "administrator"
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    config: controller.configuration
                    words: window.words
                    stationMode: window.currentPage === "stations"
                    onReveal: control => window.revealField(control)
                }
                ServerBackupsPage {
                    visible: window.state.phase === "workspace" && window.currentPage === "serverBackups" && window.administrator
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    serverBackups: controller.serverBackups
                    words: window.words
                    locale: window.state.locale
                    onReveal: control => window.revealField(control)
                }
                StaffPage {
                    visible: window.state.phase === "workspace" && window.currentPage === "staff" && window.administrator
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    staff: controller.staff
                    words: window.words
                    onReveal: control => window.revealField(control)
                }
                ComplaintCategoriesPage {
                    visible: window.state.phase === "workspace"
                        && window.currentPage === "complaintCategories" && window.administrator
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    catalog: controller.complaintCategories
                    words: window.words
                    locale: window.state.locale
                    onReveal: control => window.revealField(control)
                }
                InvalidReasonsPage {
                    visible: window.state.phase === "workspace"
                        && window.currentPage === "invalidReasons" && window.administrator
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    catalog: controller.invalidReasons
                    words: window.words
                    locale: window.state.locale
                    onReveal: control => window.revealField(control)
                }
                LifecyclePage {
                    visible: window.state.phase === "workspace" && window.currentPage === "schedule" && window.administrator
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    lifecycle: controller.lifecycle
                    words: window.words
                    onReveal: control => window.revealField(control)
                }
                ElectionCompletionPage {
                    visible: window.state.phase === "workspace"
                        && window.currentPage === "election_completion"
                        && window.state.account.role === "supervisor"
                    Layout.fillWidth: true
                    Layout.leftMargin: 28
                    Layout.rightMargin: 28
                    Layout.bottomMargin: 28
                    completion: controller.electionCompletion
                    locale: window.state.locale
                    words: window.words
                    onReveal: control => window.revealField(control)
                }
                ColumnLayout {
                    visible: window.state.phase === "workspace" && window.stationPage && !window.administrator
                    Layout.fillWidth: true
                    Layout.leftMargin: 28; Layout.rightMargin: 28; Layout.bottomMargin: 28
                    spacing: 24
                    StationWorkspace {
                        Layout.fillWidth: true
                        workspace: controller.workspace
                        words: window.words
                        onReveal: control => window.revealField(control)
                    }
                    PollingPage {
                        visible: window.currentPage === "polling"
                        Layout.fillWidth: true
                        polling: controller.polling
                        words: window.words
                        onReveal: control => window.revealField(control)
                    }
                    StockPage {
                        visible: window.currentPage === "stock"
                        Layout.fillWidth: true
                        stock: controller.stock
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    AllocationPage {
                        visible: window.currentPage === "allocations"
                        Layout.fillWidth: true
                        allocations: controller.allocations
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    StockSnapshotsPage {
                        visible: window.currentPage === "stockSnapshots"
                        Layout.fillWidth: true
                        snapshots: controller.stockSnapshots
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    SpecialPapersPage {
                        visible: window.currentPage === "specialPapers"
                        Layout.fillWidth: true
                        papers: controller.specialPapers
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    CounterReturnsPage {
                        visible: window.currentPage === "counterReturns"
                        Layout.fillWidth: true
                        returnsController: controller.counterReturns
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    TurnoutPage {
                        visible: window.currentPage === "turnout"
                        Layout.fillWidth: true
                        turnout: controller.turnout
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    FallbackPage {
                        visible: window.currentPage === "fallback"
                        Layout.fillWidth: true
                        fallback: controller.fallback
                        words: window.words
                        onReveal: control => window.revealField(control)
                    }
                    ComplaintsPage {
                        visible: window.currentPage === "complaints"
                        Layout.fillWidth: true
                        complaints: controller.complaints
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    ComplaintPeriodsPage {
                        visible: window.currentPage === "complaintPeriods"
                        Layout.fillWidth: true
                        periods: controller.complaintPeriods
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    QueuePage {
                        visible: window.currentPage === "queue"
                        Layout.fillWidth: true
                        queue: controller.queue
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    AccountingPage {
                        visible: window.currentPage === "accounting"
                        Layout.fillWidth: true
                        accounting: controller.accounting
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    RecoveryPage {
                        visible: window.currentPage === "recovery"
                        Layout.fillWidth: true
                        recovery: controller.recovery
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    OutagesPage {
                        visible: window.currentPage === "outages"
                        Layout.fillWidth: true
                        outages: controller.outages
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    CountingRoundsPage {
                        visible: window.currentPage === "countingRounds"
                        Layout.fillWidth: true
                        countingRounds: controller.countingRounds
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    ConstituencyResultsPage {
                        visible: window.currentPage === "constituency_results"
                        Layout.fillWidth: true
                        results: controller.constituencyResults
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    CountingScopesPage {
                        visible: window.currentPage === "countingScopes"
                        Layout.fillWidth: true
                        countingScopes: controller.countingScopes
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                    BoxesPage {
                        visible: window.currentPage === "boxes"
                        Layout.fillWidth: true
                        boxes: controller.boxes
                        words: window.words
                        locale: window.state.locale
                        onReveal: control => window.revealField(control)
                    }
                }
                Item { Layout.preferredHeight: 12 }
            }
        }
    }
}
