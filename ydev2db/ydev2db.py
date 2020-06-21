#!/usr/bin/env python3.8

#TODO
# Encrypt data on disk

import  json

from time import sleep, time

from   optparse import OptionParser

import  paho.mqtt.client as mqtt

from open_source_libs.p3lib.pconfig import ConfigManager
from open_source_libs.p3lib.uio import UIO
from open_source_libs.p3lib.boot_manager import BootManager
from open_source_libs.p3lib.helper import logTraceBack, GetFreeTCPPort, getHomePath, printDict
from open_source_libs.p3lib.ssh import SSH, SSHTunnelManager
from open_source_libs.p3lib.database_if import DBConfig, DatabaseIF

class YDev2DBClientConfig(ConfigManager):
    """@brief Responsible for managing the configuration used by the ydev application."""

    ICONS_ADDRESS           = "ICONS_ADDRESS"
    ICONS_PORT              = "ICONS_PORT"
    ICONS_USERNAME          = ""
    ICONS_SSH_KEY_FILE      = "ICONS_SSH_KEY_FILE"
    LOCATION                = "LOCATION"
    DEV_NAME                = "DEV_NAME"
    DB_HOST                 = "DB_HOST"
    DB_PORT                 = "DB_PORT"
    DB_USERNAME             = "DB_USERNAME"
    DB_PASSWORD             = "DB_PASSWORD"
    DB_NAME                 = "DB_NAME"
    DB_TABLE_SCHEMA         = "DB_TABLE_SCHEMA"

    DEFAULT_CONFIG = {
        ICONS_ADDRESS:              "127.0.0.1",
        ICONS_PORT:                 22,
        ICONS_USERNAME:             "",
        ICONS_SSH_KEY_FILE:         SSH.GetPrivateKeyFile(),
        LOCATION:                   "",
        DEV_NAME:                   "",
        DB_HOST:                    "127.0.0.1",
        DB_PORT:                    3306,
        DB_USERNAME:                "",
        DB_PASSWORD:                "",
        DB_NAME:                    "",
        DB_TABLE_SCHEMA:            ""
    }

    def __init__(self, uio, configFile):
        """@brief Constructor.
           @param uio UIO instance.
           @param configFile Config file instance."""
        super().__init__(uio, configFile, YDev2DBClientConfig.DEFAULT_CONFIG, addDotToFilename=False, encrypt=True)
        self._uio     = uio
        self.load()

    def configure(self):
        """@brief configure the required parameters for normal operation."""

        self.inputStr(YDev2DBClientConfig.ICONS_ADDRESS, "Enter the ICON server address", False)

        self.inputDecInt(YDev2DBClientConfig.ICONS_PORT, "Enter the ICON server port (default = 22)", minValue=1024, maxValue=65535)

        self.inputStr(YDev2DBClientConfig.ICONS_USERNAME, "Enter ICON server username", False)

        self.inputStr(YDev2DBClientConfig.ICONS_SSH_KEY_FILE, "Enter the ICON server ssh key file", False)

        self.inputStr(YDev2DBClientConfig.LOCATION, "Enter the location of the device", False)

        self.inputStr(YDev2DBClientConfig.DEV_NAME, "Enter the name of the device", False)

        self.inputStr(YDev2DBClientConfig.DB_HOST, "Enter the address of the MYSQL database server", False)

        self.inputDecInt(YDev2DBClientConfig.DB_PORT, "Enter TCP port to connect to the MYSQL database server", minValue=1024, maxValue=65535)

        self.inputStr(YDev2DBClientConfig.DB_USERNAME, "Enter the database username", False)

        self.inputStr(YDev2DBClientConfig.DB_PASSWORD, "Enter the database password", False)

        self.inputStr(YDev2DBClientConfig.DB_NAME, "Enter the database name to store the data into", False)

        self._uio.info("Example table schema")
        self._uio.info("LOCATION:VARCHAR(64) TIMESTAMP:TIMESTAMP VOLTS:FLOAT(5,2) AMPS:FLOAT(5,2) WATTS:FLOAT(10,2)")
        self.inputStr(YDev2DBClientConfig.DB_TABLE_SCHEMA, "Enter the database table schema", False)
        #Check the validity of the schema
        tableSchemaString = self.getAttr(YDev2DBClientConfig.DB_TABLE_SCHEMA)
        YDev2DBClient.GetTableSchema(tableSchemaString)
        self._uio.info("Table schema string OK")

        self.store()

class YDev2DBClient(object):
    """@Responsible for
        - Allow the user to set the configuration
        - Connecting to an ICON server, reading data from the device and storing it in a mysql database."""

    MQTT_PORT               = 1883
    LOCALHOST               = "127.0.0.1"
    MQTT_LOOP_BLOCK_SECONDS = 0.1
    DATABASE_NAME           = "YSMARTMDB"
    TIMESTAMP               = "TIMESTAMP"
    DEFAULT_LOGFILE         = "{}/ydev2db.log".format(getHomePath())

    @staticmethod
    def GetTableSchema(tableSchemaString):
        """@brief Get the table schema
           @param tableSchemaString The string defining the database table schema.
           @return A dictionary containing a database table schema."""
        timestampFound=False
        tableSchemaDict = {}
        elems = tableSchemaString.split(" ")
        if len(elems) > 0:
            for elem in elems:
                subElems = elem.split(":")
                if len(subElems) == 2:
                    colName = subElems[0]
                    if colName == YDev2DBClient.TIMESTAMP:
                        timestampFound=True
                    colType = subElems[1]
                    tableSchemaDict[colName] = colType
                else:
                    raise Exception("{} is an invalid table schema column.".format(elem))
            return tableSchemaDict
        else:
            raise Exception("Invalid Table schema. No elements found.")

        if not timestampFound:
            raise Exception("No {} table column defined.".format(YDev2DBClient.TIMESTAMP))

    def __init__(self, uio, options, config):
        """@brief Constructor
           @param uio A UIO instance
           @param options The command line options instance
           @param config A YDev2DBClientConfig instance."""
        self._uio                   = uio
        self._options               = options
        self._config                = config
        self._ssh                   = None
        self._dataBaseIF            = None
        self._addedCount            = 0
        try:
            self._tableSchema       = self.getTableSchema()
        except:
            self._tableSchema       = ""
        self._startTime             = time()

    def getTableSchema(self):
        """@return the required MYSQL table schema"""
        tableSchemaString = self._config.getAttr(YDev2DBClientConfig.DB_TABLE_SCHEMA)
        return YDev2DBClient.GetTableSchema(tableSchemaString)

    def enableAutoStart(self, user=None, argString=None):
        """@brief Enable this program to auto start when the computer on which it is installed starts."""
        bootManager = BootManager()
        if user:
            self._user = user
        bootManager.add(user=self._user, argString=argString)

    def disableAutoStart(self):
        """@brief Enable this program to auto start when the computer on which it is installed starts."""
        bootManager = BootManager()
        bootManager.remove()

    def _startSSHTunnel(self):
        """@brief Start the ssh tunnel to the SSH server"""
        sshCompression = True
        iconsAddress = self._config.getAttr(YDev2DBClientConfig.ICONS_ADDRESS)
        iconsPort = self._config.getAttr(YDev2DBClientConfig.ICONS_PORT)
        iconsUsername = self._config.getAttr(YDev2DBClientConfig.ICONS_USERNAME)
        iconsKeyFile = self._config.getAttr(YDev2DBClientConfig.ICONS_SSH_KEY_FILE)

        self._uio.info("Connecting to ICONS server: {}@{}:{}".format(iconsUsername, iconsAddress, iconsPort))
        #Build an ssh connection to the ICON server
        self._ssh = SSH(iconsAddress, iconsUsername, sshCompression, port=iconsPort, uio=self._uio, privateKeyFile=iconsKeyFile)
        self._ssh.connect(enableAutoLoginSetup=True)
        self._locaIPAddress = self._ssh.getLocalAddress()
        self._uio.info("Connected")

        self._uio.info("Setting up ssh port forwarding")
        # Get a free TCPIP port on the local machine
        localMQTTPort = GetFreeTCPPort()
        self._sshTunnelManager = SSHTunnelManager(self._uio, self._ssh, sshCompression)
        self._sshTunnelManager.startFwdSSHTunnel(localMQTTPort, YDev2DBClient.LOCALHOST, YDev2DBClient.MQTT_PORT)

        return localMQTTPort

    def _shutdownDBSConnection(self):
        """@brief Shutdown the connection to the DBS"""
        if self._dataBaseIF:
            self._dataBaseIF.disconnect()
            self._dataBaseIF = None

    def _shutdown(self):
        """@brief Shutdown all connections to the server.."""
        if self._ssh:
            self._ssh.close()
            self._uio.info("Shutdown ssh connection")
            self._ssh = None

        self._shutdownDBSConnection()

    def _connected(self, client, userdata, flags, rc):
        """@brief handle a connected ICONS session"""
        self._uio.info("Connected")

    def _showDevData(self, devDict):
        """@brief Show the device data received from the ICONS"""
        if "LOCATION" in devDict:
            location = devDict["LOCATION"]
        if "UNIT_NAME" in devDict:
            unitName = devDict["UNIT_NAME"]
        self._uio.info("")
        self._uio.info("********** {}/{} DEVICE ATTRIBUTES **********".format(location, unitName))
        printDict(self._uio, devDict)

    def _messageReceived(self, client, userdata, msg):
        """@brief Called when a message is received from the ICONS MQTT server."""
        try:
            rxStr = msg.payload.decode()
            rxDict = json.loads(rxStr)
            if self._options.show_all:
                self._showDevData(rxDict)
            else:
                if self._options.show:
                    self._showDevData(rxDict)
                self._updateDatabase(rxDict)
        except Exception as ex:
            #HAndle reconnect to DB on error
            self._uio.error( str(ex) )
            self._shutdownDBSConnection()
            try:
                self._connectToDBS()
            except Exception as ex:
                self._uio.error(str(ex))

    def _updateDatabase(self, rxDict):
        """@brief Update the database with the data received from the YSMartMeter device.
           @param rxDict The data received from the YSmartMeter device"""
        if "UNIT_NAME" in rxDict:
            if self._options.table_name:
                tableName = self._options.table_name
            else:
                tableName = rxDict["UNIT_NAME"]
                
            if not self._dataBaseIF:
                self._connectToDBS()

            devAttrDict = rxDict
            devAttrDict[YDev2DBClientConfig.LOCATION] = self._config.getAttr(YDev2DBClientConfig.LOCATION)
            self._dataBaseIF.insertRow(devAttrDict, tableName, self._tableSchema)
            self._addedCount=self._addedCount + 1
            self._uio.info("{} TABLE: Added count: {}".format(tableName, self._addedCount) )

    def _setupDBConfig(self):
        """@brief Setup the internal DB config"""
        self._dataBaseIF                    = None
        self._dbConfig                      = DBConfig()
        self._dbConfig.serverAddress        = self._config.getAttr(YDev2DBClientConfig.DB_HOST)
        self._dbConfig.username             = self._config.getAttr(YDev2DBClientConfig.DB_USERNAME)
        self._dbConfig.password             = self._config.getAttr(YDev2DBClientConfig.DB_PASSWORD)
        self._dbConfig.dataBaseName         = self._config.getAttr(YDev2DBClientConfig.DB_NAME)
        self._dbConfig.autoCreateTable      = True
        self._dbConfig.uio                  = self._uio
        self._dataBaseIF                    = DatabaseIF(self._dbConfig)

    def _connectToDBS(self):
        """@brief connect to the database server."""
        self._shutdownDBSConnection()

        self._setupDBConfig()

        self._dataBaseIF.connect()
        self._uio.info("Connected to database")

        tableName = self._config.getAttr(YDev2DBClientConfig.DEV_NAME)
        self._dataBaseIF.ensureTableExists(tableName, self._tableSchema, True)

    def readMQTT(self, host, port):
        """@brief Read from the MQTT server.
           @param host The host address of the MQTT server
           @param port The TCP port to connect to the MQTT server"""

        client = mqtt.Client(client_id="{}".format(self._startTime), clean_session=False)
        client.on_connect = self._connected
        client.on_message = self._messageReceived
        self._uio.info("MQTT client connecting to {}:{}".format(host, port))
        client.connect(host, port, 60)
        topic = "/{}/{}/#".format(self._config.getAttr(YDev2DBClientConfig.LOCATION), self._config.getAttr(YDev2DBClientConfig.DEV_NAME))
        #Subscribe to a single topic
        topic = "{}/{}/#".format(self._config.getAttr(YDev2DBClientConfig.LOCATION),
                                  self._config.getAttr(YDev2DBClientConfig.DEV_NAME))
        if self._options.show_all:
            topic="#"
        client.subscribe(topic, qos=1)

        while (self._ssh.getTransport() and self._ssh.getTransport().is_active()):
            # Loop and block here for a period of time
            client.loop(YDev2DBClient.MQTT_LOOP_BLOCK_SECONDS)

    def collectData(self, errPauseSeconds=10):
        """@brief Run the process to collect data from a connection to the MQTT server inside the ICON
                  server and save the data into a MYSQL database.
           @param errPauseSeconds The number of seconds to pause if an error occurs."""
        while True:

            try:
                try:
                    if not self._options.show_all:
                        #Check we can connect to the database
                        self._connectToDBS()

                    localMQTTPort = self._startSSHTunnel()
                    host = YDev2DBClient.LOCALHOST
                    port = localMQTTPort
                    self.readMQTT(host, port)

                except Exception as ex:
                    self._uio.error(str(ex))
                    if self._options.debug:
                        raise
                    sleep(errPauseSeconds)

            finally:
                self._shutdown()

    def createDB(self):
        """@brief Create the configured database on the MYSQL server"""
        try:
            dataBaseName = self._uio.getInput("Database to create: ")
            self._setupDBConfig()
            self._dataBaseIF.connectNoDB()

            self._dbConfig.dataBaseName = dataBaseName
            self._dataBaseIF.createDatabase()

        finally:
            self._shutdownDBSConnection()

    def deleteDB(self):
        """@brief Delete the configured database on the MYSQL server"""
        try:
            dataBaseName = self._uio.getInput("Database to delete: ")            
            self._setupDBConfig()
            self._dbConfig.dataBaseName = dataBaseName
            deleteDB = self._uio.getBoolInput("Are you sure you wish to delete the '{}' database [y/n]".format(self._dbConfig.dataBaseName))
            if deleteDB:

                self._dataBaseIF.connectNoDB()

                self._dataBaseIF.dropDatabase()

        finally:
            self._shutdownDBSConnection()

    def createTable(self):
        """@brief Create the database table configured"""
        try:
            tableName = self._uio.getInput("Table to create: ")
            self._setupDBConfig()

            self._dataBaseIF.connect()

            tableSchema = self.getTableSchema()
            self._dataBaseIF.createTable(tableName, tableSchema)

        finally:
            self._shutdownDBSConnection()

    def deleteTable(self):
        """@brief Delete a database table configured"""
        try:
            tableName = self._uio.getInput("Table to delete: ")
            self._setupDBConfig()
            deleteDBTable = self._uio.getBoolInput("Are you sure you wish to delete the '{}' database table [y/n]".format(tableName))
            if deleteDBTable:

                self._dataBaseIF.connect()

                self._dataBaseIF.dropTable(tableName)

        finally:
            self._shutdownDBSConnection()

    def showDBS(self):
        """@brief List the databases."""
        try:

            self._setupDBConfig()

            self._dataBaseIF.connectNoDB()

            sql = 'SHOW DATABASES;'
            recordTuple = self._dataBaseIF.executeSQL(sql)
            for record in recordTuple:
                self._uio.info( str(record) )

        finally:
            self._shutdownDBSConnection()

    def showTables(self):
        """@brief List the databases."""
        try:

            self._setupDBConfig()

            self._dataBaseIF.connect()

            sql = 'SHOW TABLES;'
            recordTuple = self._dataBaseIF.executeSQL(sql)
            for record in recordTuple:
                self._uio.info( str(record) )

        finally:
            self._shutdownDBSConnection()

    def readTable(self):
        """@brief Read a number of records from the end of the database table."""
        try:

            self._setupDBConfig()

            self._dataBaseIF.connect()
            
            if self._options.table_name:
                tableName = self._options.table_name
            else:
                tableName = self._config.getAttr(YDev2DBClientConfig.DEV_NAME)
                
            sql = 'SELECT * FROM `{}` ORDER BY {} DESC LIMIT {}'.format(tableName, YDev2DBClient.TIMESTAMP, self._options.read_count)
            recordTuple = self._dataBaseIF.executeSQL(sql)
            for record in recordTuple:
                self._uio.info( str(record) )

        finally:
            self._shutdownDBSConnection()
            
    def executeSQL(self):
        """@brief Execute SQL command provided on the command line."""
        try:
            sql = self._uio.getInput("SQL command to execute: ")
            self._setupDBConfig()

            self._dataBaseIF.connect()

            recordTuple = self._dataBaseIF.executeSQL(sql)
            for record in recordTuple:
                self._uio.info( str(record) )

        finally:
            self._shutdownDBSConnection()
                  
            
    def showSchema(self):
        """@brief Execute SQL command provided on the command line."""
        try:
            tableName = self._uio.getInput("SQL table to show the Schema of: ")
            self._setupDBConfig()

            self._dataBaseIF.connect()

            sql = "DESCRIBE `{}`;".format(tableName)
            recordTuple = self._dataBaseIF.executeSQL(sql)
            for record in recordTuple:
                self._uio.info( str(record) )

        finally:
            self._shutdownDBSConnection()


def main():
    uio = UIO()
    uio.logAll(True)

    opts = OptionParser(usage="Connect to an MQTT server on an ICON server, read the data from a device and store it in a mysql database.")
    opts.add_option("-f",                   help="The config file for the device to be read.")
    opts.add_option("-c",                   help="Set the configuration for your device in the above config file.", action="store_true", default=False)
    opts.add_option("--user",               help="Set the user for auto start.")
    opts.add_option("--collect",            help="Collect data from the ICONS and save to a MySQL database.", action="store_true", default=False)
    opts.add_option("--read",               help="Read a number of records from the end of the database table.", action="store_true", default=False)
    opts.add_option("--read_count",         help="The number of lines to read from the end of the database table (default=1).", type="int", default=1)
    opts.add_option("--sql",                help="Execute an SQL command.", action="store_true", default=False)
    opts.add_option("--show_dbs",           help="Show all the databases on the MySQL server.", action="store_true", default=False)
    opts.add_option("--show_tables",        help="Show all the database tables for the configured database on the MySQL server.", action="store_true", default=False)
    opts.add_option("--show_table_schema",  help="Show the schema of an SQL table.", action="store_true", default=False)
    opts.add_option("--create_db",          help="Create the configured database.", action="store_true", default=None)
    opts.add_option("--delete_db",          help="Delete the configured database.", action="store_true", default=None)
    opts.add_option("--create_table",       help="Create a table in the configured database.", action="store_true", default=None)
    opts.add_option("--delete_table",       help="Delete a table from the configured database.", action="store_true", default=None)
    opts.add_option("--enable_auto_start",  help="Enable auto start when this computer starts.", action="store_true", default=False)
    opts.add_option("--disable_auto_start", help="Disable auto start.", action="store_true", default=False)
    opts.add_option("--table_name",         help="The table name to set in the configured database. By default the ydev unit name is used.", default=None)
    opts.add_option("--log",                help="The log file (default={}".format(YDev2DBClient.DEFAULT_LOGFILE), default=YDev2DBClient.DEFAULT_LOGFILE)
    opts.add_option("--show",               help="A debug mode to show YDEV messages from the ICONS for the selected device.", action="store_true", default=False)
    opts.add_option("--show_all",           help="A debug mode to show all YDEV messages from the ICONS. No data is stored to the database if this option is used.", action="store_true", default=False)
    opts.add_option("--debug",              help="Enable debugging.", action="store_true", default=False)

    try:
        (options, args) = opts.parse_args()

        uio.setLogFile(options.log)
        uio.info("Log file: {}".format(options.log))

        yDev2DBClientConfig = YDev2DBClientConfig(uio, options.f)
        yDev2DBClient = YDev2DBClient(uio, options, yDev2DBClientConfig)

        uio.enableDebug(options.debug)
        if options.c:
            yDev2DBClientConfig.configure()

        elif options.enable_auto_start:
            yDev2DBClient.enableAutoStart(options.user, "--collect -f {} --log {}".format(options.f, options.log))

        elif options.disable_auto_start:
            yDev2DBClient.disableAutoStart()

        elif options.create_db:
            yDev2DBClient.createDB()

        elif options.delete_db:
            yDev2DBClient.deleteDB()

        elif options.create_table:
            yDev2DBClient.createTable()

        elif options.delete_table:
            yDev2DBClient.deleteTable()

        elif options.read:
            yDev2DBClient.readTable()

        elif options.show_dbs:
            yDev2DBClient.showDBS()

        elif options.show_tables:
            yDev2DBClient.showTables()

        elif options.collect or options.show_all:
            yDev2DBClient.collectData()

        elif options.sql:
            yDev2DBClient.executeSQL()
            
        elif options.show_table_schema:
            yDev2DBClient.showSchema()

        else:
            raise Exception("No action selected on command line.")

    #If the program throws a system exit exception
    except SystemExit:
        pass

    #Don't print error information if CTRL C pressed
    except KeyboardInterrupt:
        pass

    except Exception as ex:
        logTraceBack(uio)

        if options.debug:
            raise
        else:
            uio.error(str(ex))

if __name__== '__main__':
    main()
