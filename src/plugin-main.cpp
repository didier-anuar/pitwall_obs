// Pitwall - panel nativo de OBS (dock Qt) para elegir piloto y cambiar de camara.
// Habla con pitwall.py en http://127.0.0.1:9100 (/data.json, /select, /cam). Requiere OBS 30 o superior.
#include <obs-module.h>
#include <obs-frontend-api.h>

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QListWidget>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QNetworkRequest>
#include <QString>
#include <QStringList>
#include <QTimer>
#include <QUrl>
#include <QUrlQuery>
#include <QVBoxLayout>
#include <QWidget>

OBS_DECLARE_MODULE()

MODULE_EXPORT const char *obs_module_description(void)
{
	return "Pitwall: panel para elegir piloto y camara";
}

static QString U(const char16_t *text)
{
	return QString::fromUtf16(text);
}

static const QString kBase = QStringLiteral("http://127.0.0.1:9100");

class PitwallPanel : public QWidget {
public:
	explicit PitwallPanel(QWidget *parent = nullptr) : QWidget(parent)
	{
		auto *layout = new QVBoxLayout(this);
		layout->setContentsMargins(4, 4, 4, 4);

		layout->addWidget(new QLabel(U(u"C\u00e1maras"), this));
		cams_ = new QListWidget(this);
		cams_->setMaximumHeight(110);
		layout->addWidget(cams_);

		layout->addWidget(new QLabel(QStringLiteral("Pilotos"), this));
		drivers_ = new QListWidget(this);
		layout->addWidget(drivers_, 1);

		status_ = new QLabel(this);
		status_->setWordWrap(true);
		layout->addWidget(status_);

		connect(cams_, &QListWidget::itemClicked, this, [this](QListWidgetItem *item) {
			QUrl url(kBase + QStringLiteral("/cam"));
			QUrlQuery query;
			query.addQueryItem(QStringLiteral("name"), item->text());
			url.setQuery(query);
			request(url);
		});
		connect(drivers_, &QListWidget::itemClicked, this, [this](QListWidgetItem *item) {
			const int num = item->data(Qt::UserRole).toInt();
			request(QUrl(kBase + QStringLiteral("/select?car=") + QString::number(num)));
		});
		connect(&timer_, &QTimer::timeout, this, [this]() { poll(); });
		timer_.start(1500);
		poll();
	}

private:
	void poll()
	{
		QNetworkReply *reply = nam_.get(QNetworkRequest(QUrl(kBase + QStringLiteral("/data.json"))));
		connect(reply, &QNetworkReply::finished, this, [this, reply]() {
			reply->deleteLater();
			if (reply->error() != QNetworkReply::NoError) {
				status_->setText(U(u"Sin conexi\u00f3n con Pitwall. \u00bfEst\u00e1 abierto pitwall.py?"));
				return;
			}
			refresh(QJsonDocument::fromJson(reply->readAll()).object());
		});
	}

	void request(const QUrl &url)
	{
		QNetworkReply *reply = nam_.get(QNetworkRequest(url));
		connect(reply, &QNetworkReply::finished, this, [this, reply]() {
			reply->deleteLater();
			if (reply->error() != QNetworkReply::NoError) {
				status_->setText(U(u"Sin conexi\u00f3n con Pitwall"));
				return;
			}
			const QString text = QString::fromUtf8(reply->readAll());
			status_->setText(text == QStringLiteral("ok") ? QString() : text);
		});
	}

	void refresh(const QJsonObject &data)
	{
		QStringList cams;
		const QJsonArray camArray = data.value(QStringLiteral("cams")).toArray();
		for (int i = 0; i < static_cast<int>(camArray.size()); i++)
			cams << camArray.at(i).toString();
		if (cams != camNames_) {
			camNames_ = cams;
			cams_->clear();
			cams_->addItems(cams);
		}

		const int selected = data.value(QStringLiteral("selected")).toInt(0);
		const QJsonArray cars = data.value(QStringLiteral("cars")).toArray();
		const int count = static_cast<int>(cars.size());
		if (drivers_->count() != count + 1) {
			drivers_->clear();
			for (int i = 0; i < count + 1; i++)
				drivers_->addItem(new QListWidgetItem());
		}
		setRow(0, U(u"AUTO (c\u00e1mara del juego)"), 0, selected);
		for (int i = 0; i < count; i++) {
			const QJsonObject car = cars.at(i).toObject();
			const QString label = QString::number(car.value(QStringLiteral("pos")).toInt()) +
					      QStringLiteral(". ") + car.value(QStringLiteral("name")).toString();
			setRow(i + 1, label, car.value(QStringLiteral("num")).toInt(), selected);
		}
	}

	void setRow(int row, const QString &text, int num, int selected)
	{
		QListWidgetItem *item = drivers_->item(row);
		item->setText(text);
		item->setData(Qt::UserRole, num);
		if (num == selected)
			drivers_->setCurrentItem(item);
	}

	QListWidget *cams_ = nullptr;
	QListWidget *drivers_ = nullptr;
	QLabel *status_ = nullptr;
	QNetworkAccessManager nam_;
	QTimer timer_;
	QStringList camNames_;
};

bool obs_module_load(void)
{
	auto *panel = new PitwallPanel();
	if (!obs_frontend_add_dock_by_id("pitwall_panel", "Pitwall", panel)) {
		delete panel;
		blog(LOG_WARNING, "[pitwall] no se pudo crear el panel (se necesita OBS 30 o superior)");
		return true;
	}
	blog(LOG_INFO, "[pitwall] panel cargado");
	return true;
}
