from utility import ConvertImage, Df_Csv_single
import argparse, logging


 # Initialize the logger
logging.basicConfig(format='%(asctime)s - %(name)-8s - %(levelname)-8s - %(message)s',
                    datefmt='%d-%b-%y %H:%M:%S')
logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

    # Setup the argument parsing
def main():
    logger.info("Parsing arguments...")
    parser = argparse.ArgumentParser(prog='main', description='Everything you need to start a Feature Extraction plugin.')
    parser.add_argument('--features', dest='features', type=str,
                        help='Features to calculate', required=True)
    parser.add_argument('--csvfile', dest='csvfile', type=str,
                        help='Save csv as separate or single file', required=True)
    parser.add_argument('--angleDegree', dest='angleDegree', type=int,
                        help='Angle to calculate feret diameter', required=False)
    parser.add_argument('--boxSize', dest='boxSize', type=int,
                        help='Boxsize to calculate neighbors and feret diameter', required=False)
    parser.add_argument('--intDir', dest='intDir', type=str,
                        help='Intensity image collection', required=False)
    parser.add_argument('--pixelDistance', dest='pixelDistance', type=int,
                        help='Pixel distance to calculate the neighbors touching cells', required=False)
    parser.add_argument('--segDir', dest='segDir', type=str,
                        help='Segmented image collection', required=True)
    parser.add_argument('--outDir', dest='outDir', type=str,
                        help='Output collection', required=True)

    # Parse the arguments
    args = parser.parse_args()
    features = args.features.split(',')#features
    logger.info('features = {}'.format(features))
    csvfile = args.csvfile#csvfile
    logger.info('csvfile = {}'.format(csvfile))
    angleDegree = args.angleDegree#angle to calculate feret diameter
    logger.info('angleDegree = {}'.format(angleDegree))
    boxSize = args.boxSize#box size to calculate neighbors and feret diameter
    logger.info('boxSize = {}'.format(boxSize))
    intDir = args.intDir#intensity image
    logger.info('intDir = {}'.format(intDir))
    pixelDistance = args.pixelDistance#pixel distance to calculate neighbors
    logger.info('pixelDistance = {}'.format(pixelDistance))
    segDir = args.segDir#segmented image
    logger.info('segDir = {}'.format(segDir))
    outDir = args.outDir#directory to save output files
    logger.info('outDir = {}'.format(outDir))
    logger.info("Started")
    image_convert = ConvertImage(segDir,intDir)
    
    df,filenames= image_convert.convert_tiled_tiff(features,csvfile,outDir,boxSize, angleDegree, pixelDistance)
    #call csv function to save as a single file
    if csvfile == 'csvone':
        csv_file= Df_Csv_single(df, outDir)
        csv_final = csv_file.csvfilesave()
        del csv_final
        del df
        del filenames

    logger.info("Finished all processes!")

if __name__ == "__main__":
    main()
    
    
